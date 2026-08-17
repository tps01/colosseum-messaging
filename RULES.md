## Approved Software Licenses

Only the following licenses are allowed:

- Apache License 2.0
- Boost Software License
- BSD 2-Clause License
- BSD 3-Clause License
- CMU/CMD License
- CPL v1.0
- CPOL v1.02
- ISC License
- ICU License 1.8.1
- Microsoft Public License
- MIT License
- Expat License
- MIT-X11 License
- X11 License
- X License
- MIT/X Consortium License
- GNU Lesser General Public License (LGPL) — allowed only when used unmodified (no source modifications)
- NASA Open Source Agreement 1.3
- Public Domain
- Python Software Foundation License v2 (Python 2.0.1 and greater)
- SGI Free Software License B v2.0
- SIL Open Font License (OFL) 1.1
- Ubuntu Font License 1.0
- Unicode License
- Unlicense
- W3C Software and Document License
- W3C Software Notice and License
- Zlib License

---

# What This Means in Practice

- Before adding or updating dependencies, verify license compatibility against this allowlist.
- If dependency license metadata is ambiguous, treat it as unapproved until clarified.
- LGPL dependencies are allowed only if the LGPL-covered source is not modified in this project.
- If LGPL-covered source modifications are required, treat as non-compliant unless explicitly re-approved and documented before merge.
- If a dependency violates this rule, do not add it; propose a compliant alternative.
- If an existing dependency is found non-compliant, flag it immediately for remediation.

## Messaging dependency notes

- HTTP uses stdlib `urllib.request` (no `httpx`/`requests`/`certifi`).
- `paho-mqtt` is dual-licensed EPL-2.0 OR EDL-1.0; this project consumes it under **EDL-1.0** (BSD-3 equivalent).
- `pyzmq` wheels bundle unmodified libzmq (LGPL).
- `paramiko` is LGPL unmodified.


## Unit Testing

- Only write high value unit tests.
- Do not prioritize code coverage for the sake of coverage. Better coverage can be achieved by keeping the project small and maintainable.
