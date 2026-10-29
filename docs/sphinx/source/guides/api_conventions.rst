API conventions and failures
============================

Call public APIs through ``import colosseum as col`` and the documented
``col.*`` path. Signatures show defaults and keyword-only arguments (after
``*``). Omitted optional arguments use those defaults; a required argument has
no default. See each callable for its units and driver-specific restrictions.

Commands record actions and re-raise exceptions unless ``optional=True``.
Measurements record returned evidence under ``key``; an exception records a
null ERROR row and re-raises unless ``optional=True``, which returns ``None``.
Verification FAIL/ERROR/BLOCKED outcomes are recorded without aborting later
steps. ``optional=True`` excludes an outcome from the aggregate verdict; it
does not make a later dependent verification optional.

Keep measurement keys distinct for separate facts. Instrument IDs and channels
do not distinguish measurements with the same domain, command, key, and row
index. See `evidence and verification <https://tps01.github.io/colosseum-core/guides/measurements_verifications.html>`__
for lookup rules and complete failure examples.

The plugin uses Colosseum's standard run artifacts. See the
`output guide <https://tps01.github.io/colosseum-core/guides/output_artifacts.html>`__
for summaries and SQLite queries. Plugin captures require artifacts enabled.

See :doc:`protocol_workflows` for protocol-specific failure categories.
