"""Brain detectors. Each module exposes ``detect(vessel, context) -> list[finding]``.

The finding format and the rules for detector authors are in ``argus.assemble``.
Connect a detector by adding it to ``argus.assemble.DETECTORS``.
"""
