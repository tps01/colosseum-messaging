"""Messaging plugin documentation spec."""

from colosseum.docgen_spec import DocgenModuleSpec


def spec() -> DocgenModuleSpec:
    return DocgenModuleSpec(
        module_id="colosseum_messaging",
        title="Colosseum Messaging",
        import_packages=["colosseum_messaging"],
        autodoc_modules=["colosseum_messaging"],
        order=40,
        namespace="messaging",
    )
