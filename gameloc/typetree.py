# Gameloc — 게임 폴더를 넣으면 번역해 주는 도구
# Copyright (C) 2026  하진
#
# 이 프로그램은 자유 소프트웨어입니다. 자유 소프트웨어 재단이 펴낸 GNU 일반
# 공중 사용 허가서 3판 또는 그 이후 판의 조건에 따라 재배포하거나 고칠 수
# 있습니다.
#
# 이 프로그램은 쓸모가 있기를 바라며 배포하지만 어떠한 보증도 하지 않습니다.
# 자세한 내용은 GNU 일반 공중 사용 허가서를 보세요.
# 함께 받은 LICENSE 파일에 전문이 있습니다. <https://www.gnu.org/licenses/>

"""유니티 빌드에서 사라진 '타입 정보' 를 게임의 DLL 로 되살립니다.

## 왜 필요한가

유니티는 배포 빌드에 **MonoBehaviour 의 타입 정보를 넣지 않습니다.** 엔진이
직접 아는 타입(Texture2D 등)은 괜찮지만, 게임이 직접 만든 스크립트는 무엇이
어떤 필드였는지가 파일에 안 적혀 있습니다. 그래서 그냥 열면 이렇게 나옵니다:

    MonoBehaviour 2710개 (타입정보 읽음 21, 못 읽음 2689)

대사는 대개 저 2689개 안에 있습니다. 21개만 읽고 '번역할 게 없다' 고 하면
사실은 다 못 본 겁니다.

## 어떻게 되살리나

타입 정보는 게임의 코드 안에 그대로 남아 있습니다.

    Mono 빌드   : <게임>_Data/Managed/*.dll
    IL2CPP 빌드 : GameAssembly.dll + il2cpp_data/Metadata/global-metadata.dat

여기서 클래스 구조를 읽어 타입 정보를 다시 만들어 주면 나머지 오브젝트가
전부 열립니다. ``TypeTreeGeneratorAPI`` 가 그 일을 합니다 — 없어도 프로그램은
그냥 예전처럼 동작하고, 있으면 훨씬 많이 찾습니다.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE = "TypeTreeGeneratorAPI"

_cache: dict[str, object] = {}
_failed: set[str] = set()


def available() -> bool:
    try:
        import TypeTreeGeneratorAPI  # noqa: F401
    except ImportError:
        return False
    return True


def install_hint() -> str:
    return (f"MonoBehaviour 타입 정보를 되살리려면 {PACKAGE} 가 필요합니다.\n"
            f"    pip install {PACKAGE}\n"
            "설치하면 게임의 DLL 에서 구조를 읽어 훨씬 많은 문장을 찾습니다.")


def _sources(root: Path) -> tuple[Path | None, Path | None, Path | None]:
    """``(Managed 폴더, GameAssembly.dll, global-metadata.dat)``."""
    data = next((p for p in sorted(root.glob("*_Data")) if p.is_dir()), None)
    if data is None:
        data = root
    managed = data / "Managed"
    ga = root / "GameAssembly.dll"
    meta = data / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    return (managed if managed.is_dir() else None,
            ga if ga.is_file() else None,
            meta if meta.is_file() else None)


def describe(root: Path) -> str:
    managed, ga, meta = _sources(Path(root))
    if managed:
        n = len(list(managed.glob("*.dll")))
        return f"Mono 빌드 · Managed/ 안 dll {n}개"
    if ga and meta:
        return "IL2CPP 빌드 · GameAssembly.dll + global-metadata.dat"
    return "타입 정보를 되살릴 코드 파일을 찾지 못했습니다"


def generator(root: Path, unity_version: str):
    """``env.typetree_generator`` 에 꽂을 물건. 못 만들면 ``None``."""
    root = Path(root)
    key = f"{root}|{unity_version}"
    if key in _cache:
        return _cache[key]
    if key in _failed or not unity_version:
        return None

    try:
        from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
    except ImportError:
        _failed.add(key)
        return None

    managed, ga, meta = _sources(root)
    try:
        gen = _fixed_class(TypeTreeGenerator)(unity_version)
        if managed is not None:
            gen.load_local_dll_folder(str(managed))
        elif ga is not None and meta is not None:
            gen.load_il2cpp(ga.read_bytes(), meta.read_bytes())
        else:
            _failed.add(key)
            return None
    except Exception:                    # noqa: BLE001 - 없으면 그냥 예전처럼
        _failed.add(key)
        return None

    _install_ref_reader()
    _cache[key] = gen
    return gen


# ---------------------------------------------------------------------------
# 생성기가 만든 타입 정보를 바로잡습니다
#
# ## ① List<string> 이 'string' 으로 나옵니다
#
# 생성기는 목록 필드의 타입 이름을 ``vector`` 가 아니라 **원소 타입** 으로
# 적습니다. 원소가 클래스일 때는 UnityPy 가 자식 모양(Array)을 보고 목록으로
# 읽어 주지만, 원소가 ``string``·``int`` 처럼 UnityPy 가 이름만 보고 바로 읽는
# 타입이면 **목록을 값 하나로 읽어 버립니다.** 그 뒤로 전부 어긋납니다.
#
#     string _doing            ← 사실은 List<string>
#       Array Array
#         int size
#         string data          ← 진짜 string 이면 여기가 'char data'
#
# 실제 게임(ニートの俺は…)의 ``MotherTrackingLocationMaster._doing``,
# ``CharacterMaster._speakerNameAliases`` 가 이래서 못 읽혔습니다.
#
# ## ② [SerializeReference] 가 통째로 안 읽힙니다
#
# ``[SerializeReference]`` 로 저장한 필드는 오브젝트 끝의 ``references`` 목록에
# 실제 클래스 이름과 함께 따로 들어갑니다. UnityPy 는 그 클래스의 구조를
# 파일 머리의 ``ref_types`` 에서 찾는데, **배포 빌드는 그 칸이 비어 있습니다.**
# 그래서 "Failed to get ref type node" 로 오브젝트 전체를 못 읽고, 바이트
# 훑기로 넘어가 필드 구분 없이 일본어를 긁어 왔습니다 — 대사와 **토픽 이름
# (NickName)** 이 한데 섞여 번역되던 원인입니다.
#
# 구조는 DLL 에 있으니 여기서도 생성기로 만들어 줍니다. 단, 생성기는 어떤
# 클래스든 MonoBehaviour 머리(m_GameObject·m_Enabled·m_Script·m_Name)를 붙여
# 돌려주므로, 참조 데이터용으로는 그 머리를 떼어 내야 바이트가 맞습니다.
# ---------------------------------------------------------------------------

# UnityPy 가 이름만 보고 바로 읽는 타입. 이 이름에 Array 자식이 붙어 있으면
# 목록입니다(단, 진짜 string 은 'char data' 를 자식으로 가집니다).
_DIRECT = {
    "bool", "SInt8", "UInt8", "char", "SInt16", "short", "UInt16",
    "unsigned short", "SInt32", "int", "Type*", "UInt32", "unsigned int",
    "SInt64", "long long", "UInt64", "unsigned long long", "FileSize",
    "float", "double", "string", "TypelessData", "ByteArray",
}
_MB_HEAD = {"m_GameObject", "m_Enabled", "m_Script", "m_Name"}


def _fix_vectors(nodes: list) -> list:
    """목록인데 원소 타입 이름이 붙은 노드를 ``vector`` 로 고칩니다."""
    for i, n in enumerate(nodes):
        if n.m_Type not in _DIRECT or i + 2 >= len(nodes):
            continue
        arr, size = nodes[i + 1], nodes[i + 2]
        if arr.m_Type != "Array" or arr.m_Level != n.m_Level + 1:
            continue
        data = next((m for m in nodes[i + 3:] if m.m_Level <= arr.m_Level + 1),
                    None)
        if data is None or data.m_Level != arr.m_Level + 1:
            continue
        if n.m_Type == "string" and data.m_Type == "char":
            continue                      # 진짜 문자열
        if size.m_Type in ("int", "SInt32") and n.m_Type != "TypelessData":
            n.m_Type = "vector"
    return nodes


def _strip_head(nodes: list) -> list:
    """MonoBehaviour 머리 필드를 떼어 낸 노드 목록 (참조 데이터용)."""
    out, skip = [], None
    for n in nodes:
        if skip is not None:
            if n.m_Level > skip:
                continue
            skip = None
        if n.m_Level == 1 and n.m_Name in _MB_HEAD:
            skip = 1
            continue
        out.append(n)
    return out


def _fixed_class(base):
    class Fixed(base):
        """``get_nodes`` 결과를 바로잡은 생성기. ``get_nodes_up`` 도 이걸 씁니다."""

        def get_nodes(self, assembly, fullname):
            return _fix_vectors(list(super().get_nodes(assembly, fullname)))

        def get_ref_nodes(self, assembly, fullname):
            """``[SerializeReference]`` 데이터용 노드 (머리 없음)."""
            from UnityPy.helpers.TypeTreeNode import TypeTreeNode
            refs = self.__dict__.setdefault("_ref_cache", {})
            key = (assembly, fullname)
            if key not in refs:
                asm = assembly if assembly.endswith(".dll") else f"{assembly}.dll"
                nodes = _strip_head(self.get_nodes(asm, fullname))
                refs[key] = TypeTreeNode.from_list([
                    TypeTreeNode(n.m_Level, n.m_Type, n.m_Name, 0, 0,
                                 m_MetaFlag=n.m_MetaFlag)
                    for n in nodes])
            return refs[key]

    Fixed.__name__ = f"Fixed{base.__name__}"
    return Fixed


_ref_installed = False


def _install_ref_reader() -> None:
    """UnityPy 가 참조 데이터의 구조를 게임 DLL 에서 찾게 합니다 (한 번만)."""
    global _ref_installed
    if _ref_installed:
        return
    try:
        from UnityPy.helpers import TypeTreeHelper as tth
    except ImportError:
        return
    original_lookup = tth.get_ref_type_node
    original_read = tth.read_typetree

    from UnityPy.helpers.TypeTreeNode import TypeTreeNode
    # 빈 참조(null)는 데이터가 0바이트입니다. UnityPy 는 읽을 때 None 을 받으면
    # 'data' 칸을 아예 빼 버리고, 쓸 때는 그 칸을 찾다가 KeyError 로 죽습니다.
    # 자식 없는 구조를 주면 읽기는 {} 가 되고 쓰기도 아무것도 안 써서 맞습니다.
    empty = TypeTreeNode(0, "ReferencedObjectData", "Base", 0, 0)

    def lookup(ref_object, assetfile):
        typ = ref_object["type"]
        if isinstance(typ, dict):
            cls, ns, asm = typ["class"], typ["ns"], typ["asm"]
        else:
            cls, ns, asm = getattr(typ, "class"), typ.ns, typ.asm
        if not cls:
            return empty
        try:
            found = original_lookup(ref_object, assetfile)
        except Exception:                # noqa: BLE001 - 아래에서 되살립니다
            found = None
        if found is not None:
            return found
        env = getattr(assetfile, "environment", None) if assetfile else None
        gen = getattr(env, "typetree_generator", None)
        make = getattr(gen, "get_ref_nodes", None)
        if make is None:
            raise ValueError(f"Referenced type not found: {cls} {ns} {asm}")
        return make(asm, f"{ns}.{cls}" if ns else cls)

    def read(root_node, reader, as_dict=True, byte_size=None,
             check_read=True, assetsfile=None):
        pos = reader.Position
        try:
            return original_read(root_node, reader, as_dict=as_dict,
                                 byte_size=byte_size, check_read=check_read,
                                 assetsfile=assetsfile)
        except Exception:
            # 빠른 C 경로는 참조 구조를 파일 머리에서만 찾습니다. 참조가 든
            # 오브젝트면 파이썬 경로(위 lookup 을 씀)로 한 번 더 읽습니다.
            if not _has_refs(root_node):
                raise
        reader.Position = pos
        config = tth.TypeTreeConfig(as_dict, assetsfile, False)
        obj = tth.read_value(root_node, reader, config)
        got = reader.Position - pos
        if check_read and byte_size is not None and got != byte_size:
            raise ValueError(
                f"Expected to read {byte_size} bytes, but only read {got} bytes")
        return obj

    tth.get_ref_type_node = lookup
    tth.read_typetree = read
    _ref_installed = True


def _has_refs(node) -> bool:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.m_Type in ("ReferencedObject", "ManagedReferencesRegistry"):
            return True
        stack.extend(n.m_Children or ())
    return False


class _Guarded:
    """실패가 이어지면 **스스로 물러나는** 타입 정보 생성기.

    ## 못 읽은 클래스를 기억합니다

    UnityPy 는 성공만 기억하고 실패는 안 기억합니다. 그래서 못 읽는 클래스가
    하나 있으면, 그 클래스를 쓰는 오브젝트가 5,000개일 때 .NET 을 5,000번
    다시 부릅니다. 매번 똑같이 실패하면서요. 한 번 실패한 클래스를 기억해
    두면 **파일 하나에 클래스 수십 종류만큼**으로 끝납니다.

    ## '몇 번 실패하면 손 뗀다' 는 넣지 마세요 — 될 것까지 막았습니다

    1.1.1 에 "한 번도 성공 못 한 채 40번 실패하면 물러난다" 를 넣었습니다.
    오브젝트마다 비용이 든다고 착각해서였습니다. 그런데 위의 기억하기가
    이미 비용을 없애 주므로 필요가 없었고, 오히려 해로웠습니다.

        level1   MonoBehaviour 5633개 — 물러남 ×4811   ← 시도조차 안 함
        level15  MonoBehaviour 3343개 — 읽음 528       ← 같은 게임인데 됨

    같은 게임에서도 파일에 따라 되는 클래스가 있는데, 앞의 40개가 실패했다는
    이유로 **뒤에 있는 TextMeshPro 폰트를 시도조차 안 했습니다.** 폰트를
    고치려면 그 구조를 읽어야 하는데, 그래서 "구조를 읽지 못했습니다" 가
    떴습니다. 되는 것까지 막은 셈입니다.

    ## .NET 이 직접 찍는 글은 막지 않습니다 — 막으려다 죽었습니다

    생성기는 클래스를 못 찾을 때마다 ``Error generating tree nodes:`` 를
    파이썬이 아니라 **.NET 쪽에서 직접** 화면에 찍습니다. 1.1.1 에서 이걸
    막으려고 운영체제 수준의 출력 통로(1·2번)를 잠깐 돌려놨는데,
    **큰 게임에서 프로그램이 통째로 죽었습니다.**

      · 타입 정보를 볼 때마다 실행됩니다. 오브젝트 38,242개면 통로 조작만
        30만 번입니다
      · 번역 작업과 화면 응답이 **동시에** 도는데, 한쪽이 통로를 바꿔치기
        하는 중에 다른 쪽이 그 통로를 쓰면 어긋납니다
      · 윈도우 콘솔에서 특히 불안정합니다

    그리고 **막을 필요도 없습니다.** 바로 아래 '못 읽은 클래스 기억하기' 가
    같은 일을 안전하게 합니다 — 클래스마다 한 번만 물어보므로 도배가 안
    생깁니다. 다시 넣지 마세요.
    """

    def __init__(self, gen):
        self._gen = gen
        self.ok = 0
        self.fails = 0
        # **안 되는 클래스를 기억합니다.** UnityPy 는 성공만 기억하고 실패는
        # 안 기억해서, 못 읽는 클래스가 나올 때마다 .NET 을 다시 부릅니다.
        # 같은 클래스의 오브젝트가 수천 개면 수천 번을 다시 부르는 셈이라,
        # 큰 게임에서 몇 분씩 멈춰 있는 것처럼 보입니다.
        self.bad: set = set()

    def __getattr__(self, name):
        return getattr(self._gen, name)

    def _call(self, fn, *a):
        if a in self.bad:
            raise RuntimeError("이미 못 읽은 클래스입니다")
        try:
            out = fn(*a)
        except Exception:
            self.bad.add(a)
            self.fails += 1
            raise
        self.ok += 1
        return out

    def get_nodes_up(self, assembly, fullname):
        return self._call(self._gen.get_nodes_up, assembly, fullname)

    def get_nodes(self, assembly, fullname):
        return self._call(self._gen.get_nodes, assembly, fullname)


def attach(env, root: Path, unity_version: str):
    """UnityPy 환경에 타입 정보 생성기를 붙입니다. 붙였으면 그 물건을."""
    gen = generator(root, unity_version)
    if gen is None:
        return None
    guard = _Guarded(gen)
    try:
        env.typetree_generator = guard
    except Exception:                    # noqa: BLE001
        return None
    return guard


def reset() -> None:
    _cache.clear()
    _failed.clear()
