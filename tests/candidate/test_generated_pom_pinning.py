"""Layer 10: the generated build files are pinned, so an offline build is reproducible.

Every runtime target emits a ``pom.xml``.  A floating version (a range, ``LATEST``/``RELEASE``/``SNAPSHOT``) would make the build depend on whatever
a repository serves that day, defeating the offline image's pre-cached set and the byte-reproducibility Layer 9 proves.  The poms are generated from the
same small program for each of the five targets and checked structurally.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from engine.transformation.runtime_registry import RUNTIME_KEYS
from tests.application_ir.test_l9_generation_authority import prog
from tests.application_ir.test_l9_generation_record import run

FLOATING = re.compile(r"LATEST|RELEASE|SNAPSHOT|^[\[(]|[\])]$|,", re.IGNORECASE)


def _text(element: ET.Element, tag: str, ns: str) -> str:
    found = element.find(f"{ns}{tag}")
    return (found.text or "").strip() if found is not None else ""


@pytest.fixture(scope="module", params=RUNTIME_KEYS)
def pom(request, tmp_path_factory):
    report = run(tmp_path_factory.mktemp(request.param), request.param, {"main.cob": prog("MAIN")}, "MAIN")
    assert report.generation_success, report.generation_errors
    path = Path(report.generated_project_dir) / "pom.xml"
    assert path.is_file()
    root = ET.parse(path).getroot()
    return request.param, root, root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""


def test_no_declared_version_floats(pom):
    runtime, root, ns = pom
    own = root.find(f"{ns}version")  # the generated artifact's own version, not something the build fetches
    versions = [(el.tag.split("}")[-1], (el.text or "").strip()) for el in root.iter() if el is not own
                and el.tag.split("}")[-1].endswith("version") and (el.text or "").strip()]
    assert versions, runtime
    assert not [(tag, value) for tag, value in versions if FLOATING.search(value)], (runtime, versions)


def test_every_declared_property_version_is_a_concrete_release(pom):
    runtime, root, ns = pom
    properties = root.find(f"{ns}properties")
    declared = {} if properties is None else {p.tag.split("}")[-1]: (p.text or "").strip() for p in properties}
    for name, value in declared.items():
        if name.endswith(".version") or name.endswith("-version"):
            assert re.fullmatch(r"\d+(\.\d+)*([.-][A-Za-z0-9]+)?", value), (runtime, name, value)


def test_every_explicit_plugin_and_dependency_version_is_concrete_or_a_property(pom):
    runtime, root, ns = pom
    for kind in ("plugin", "dependency"):
        for element in root.iter(f"{ns}{kind}"):
            version = _text(element, "version", ns)
            assert not version or re.fullmatch(r"\d[\w.\-]*|\$\{[\w.\-]+\}", version), (runtime, kind, version)


def test_the_java_release_is_declared_concretely(pom):
    runtime, root, _ns = pom
    releases = [(el.text or "").strip() for el in root.iter()
                if el.tag.split("}")[-1] in ("maven.compiler.release", "java.version", "release")]
    assert releases and set(releases) <= {"17", "21"}, (runtime, releases)
