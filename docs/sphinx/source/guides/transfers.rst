Transfer selection and evidence
===============================

Prepare a local ``settings.json`` and a writable remote scratch directory before
using this live SFTP fragment::

   col.messaging.ssh.mkdir(ssh_id=1, path="/tmp/colosseum-example")
   col.messaging.ssh.put(ssh_id=1, local="settings.json", remote="/tmp/colosseum-example/settings.json")
   col.messaging.ssh.listdir(ssh_id=1, path="/tmp/colosseum-example", key="files")
   col.messaging.ssh.get(ssh_id=1, remote="/tmp/colosseum-example/*.json", local="sftp", newest=1, key="download")
   col.messaging.ssh.remove(ssh_id=1, path="/tmp/colosseum-example/settings.json")

``scp.put`` and ``scp.get`` offer the same transfer selection using ``ssh_id``;
live SCP requires the remote SCP program as well as SSH. Upload ``local`` paths
are local files. Download ``local`` paths resolve under the run output directory;
``get`` returns a list of saved local paths as measurement evidence. ``listdir``
records the remote name list. ``put``, ``mkdir`` and ``remove`` record command
outcomes. Use distinct keys for independent acquisitions.

Using the same prepared local file and remote scratch directory::

   col.messaging.scp.put(ssh_id=1, local="settings.json", remote="/tmp/colosseum-example/settings.json")
   col.messaging.scp.get(ssh_id=1, remote="/tmp/colosseum-example/settings.json", local="scp/settings.json", key="scp_download")

``recursive=True`` descends directories; ``max_depth`` bounds descent.
``newest`` / ``oldest`` select by remote modification time and are mutually
exclusive. Globs are resolved by the plugin, not a remote shell. A glob matches
file basenames throughout the selected tree and does not filter directory
names. Windows drive paths are accepted and matching is platform-aware. This
is selection of files, not a guarantee that a producer has finished writing
them.

Verification-only reuses recorded responses/results for row-based verifiers.
It does not contact a server to repeat skipped acquisitions, download missing
files, or recover background jobs. Keep downloaded files accessible if later
checks read their contents.

Load the ``messaging.ssh`` configuration from :doc:`ssh`; SCP reuses ``ssh_id``.
See :doc:`/api/ssh`, :doc:`/api/scp`, and :doc:`/config_reference`. A download
row records saved local paths. Later content verification needs those files
to remain accessible, not just their SQLite row.
