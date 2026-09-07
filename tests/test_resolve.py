"""Resolving trace paths onto real files, and refusing to guess.

The rule under test throughout: a suffix match is used only when it is unique.
Putting the wrong file in a packet is worse than putting none in, because the
agent reading it will edit the wrong file with confidence.
"""

from pathlib import Path

from bugpacket.models import Frame
from bugpacket.resolve import FrameResolver


def write(root: Path, rel: str, text: str = "x = 1\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def frame(path: str, line: int = 1, **kwargs) -> Frame:
    kwargs.setdefault("function", None)
    kwargs.setdefault("language", "python")
    return Frame(path=path, line=line, **kwargs)


def test_direct_resolution_of_a_relative_path(tmp_path):
    write(tmp_path, "src/app.py")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("src/app.py"))
    assert result.how == "direct"
    assert result.path == (tmp_path / "src/app.py").resolve()


def test_direct_resolution_is_relative_to_cwd_not_only_root(tmp_path):
    write(tmp_path, "sub/app.py")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path / "sub")
    assert resolver.resolve(frame("app.py")).how == "direct"


def test_suffix_match_finds_a_file_the_trace_could_not_name(tmp_path):
    """A `go test` failure names `pricing_test.go` with no directory."""
    write(tmp_path, "pricing/pricing_test.go")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("pricing_test.go", language="go"))
    assert result.how == "suffix"
    assert result.path == (tmp_path / "pricing/pricing_test.go").resolve()


def test_suffix_match_survives_a_build_path_that_no_longer_exists(tmp_path):
    """A Go panic records the absolute path the binary was BUILT at."""
    write(tmp_path, "cart/cart.go")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("/build/ci/shop/cart/cart.go", language="go"))
    assert result.how == "suffix"
    assert result.path == (tmp_path / "cart/cart.go").resolve()


def test_two_files_with_the_same_name_resolve_to_neither(tmp_path):
    write(tmp_path, "alpha/util_test.go")
    write(tmp_path, "beta/util_test.go")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("util_test.go", language="go"))
    assert result.how == "ambiguous"
    assert result.path is None
    assert result.candidates == ("alpha/util_test.go", "beta/util_test.go")


def test_longer_suffix_wins_over_an_ambiguous_shorter_one(tmp_path):
    """`shop/cart/cart.go` picks one even though `cart.go` alone would not."""
    write(tmp_path, "shop/cart/cart.go")
    write(tmp_path, "vendor/cart/cart.go")
    write(tmp_path, "other/cart.go")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("/build/shop/cart/cart.go", language="go"))
    assert result.how == "suffix"
    assert result.path == (tmp_path / "shop/cart/cart.go").resolve()


def test_jvm_package_hint_disambiguates_a_common_file_name(tmp_path):
    """Two `Pricing.java` files; only the package says which one ran."""
    write(tmp_path, "billing/src/main/java/com/example/shop/Pricing.java")
    write(tmp_path, "legacy/src/main/java/com/other/app/Pricing.java")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(
        frame(
            "Pricing.java",
            line=8,
            language="jvm",
            path_hint="com/example/shop/Pricing.java",
        )
    )
    assert result.how == "suffix"
    assert (
        result.path == (tmp_path / "billing/src/main/java/com/example/shop/Pricing.java").resolve()
    )


def test_jvm_without_a_usable_hint_still_refuses_when_ambiguous(tmp_path):
    write(tmp_path, "a/Pricing.java")
    write(tmp_path, "b/Pricing.java")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("Pricing.java", language="jvm"))
    assert result.how == "ambiguous"


def test_vendored_frame_is_never_searched_for(tmp_path):
    """A repo with its own map.rs must not absorb std's HashMap frame."""
    write(tmp_path, "src/map.rs")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(
        frame("/toolchain/lib/rustlib/src/rust/library/std/src/map.rs", language="rust")
    )
    assert result.how == "vendored"
    assert result.path is None


def test_vendored_flag_on_the_frame_is_honoured(tmp_path):
    write(tmp_path, "src/HashMap.java")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("HashMap.java", language="jvm", vendored=True, path_hint=None))
    assert result.how == "vendored"


def test_absolute_path_that_exists_outside_the_repo_is_not_searched_for(tmp_path):
    """The frame named a real file; it is simply not part of this project."""
    outside = tmp_path / "outside"
    outside.mkdir()
    real = write(outside, "shared/config.py")
    repo = tmp_path / "repo"
    write(repo, "app/config.py")
    resolver = FrameResolver(repo_root=repo, cwd=repo)
    result = resolver.resolve(frame(str(real)))
    assert result.how == "outside-repo"
    assert result.path is None


def test_skipped_directories_are_not_indexed(tmp_path):
    write(tmp_path, "node_modules/pkg/index.js")
    write(tmp_path, ".venv/lib/index.js")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    assert resolver.resolve(frame("index.js", language="node")).how == "unresolved"


def test_a_skipped_directory_does_not_create_false_ambiguity(tmp_path):
    """One real match plus a copy under node_modules is still one match."""
    write(tmp_path, "src/checkout.js")
    write(tmp_path, "node_modules/dep/checkout.js")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("checkout.js", language="node"))
    assert result.how == "suffix"
    assert result.path == (tmp_path / "src/checkout.js").resolve()


def test_windows_separators_and_dot_slash_are_folded(tmp_path):
    write(tmp_path, "pkg/mod/thing.py")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    assert resolver.resolve(frame(r"build\pkg\mod\thing.py")).how == "suffix"
    assert resolver.resolve(frame("./pkg/mod/thing.py")).how == "direct"


def test_unknown_file_name_is_unresolved_not_ambiguous(tmp_path):
    write(tmp_path, "src/app.py")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("nowhere.py"))
    assert result.how == "unresolved"
    assert result.candidates == ()


def test_resolve_path_handles_a_bare_test_file(tmp_path):
    write(tmp_path, "tests/test_cart.py")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    assert resolver.resolve_path("test_cart.py") == (tmp_path / "tests/test_cart.py").resolve()


def test_a_directory_matching_the_name_is_not_a_resolution(tmp_path):
    (tmp_path / "build" / "app.py").mkdir(parents=True)
    write(tmp_path, "src/app.py")
    resolver = FrameResolver(repo_root=tmp_path, cwd=tmp_path)
    result = resolver.resolve(frame("app.py"))
    assert result.path == (tmp_path / "src/app.py").resolve()
