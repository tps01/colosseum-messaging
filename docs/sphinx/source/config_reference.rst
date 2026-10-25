Config reference
================

A config row is one TOML table. One row uses ``[dotted.path]``. Use
``[[dotted.path]]`` only when the sample shows two or more rows of that same
section, such as two ZMQ sockets. When the section is present, the integer id
field is required. Comments below come from each client constructor.

messaging.http
--------------

.. code-block:: toml

   [messaging.http]
   http_id = 1                         # required integer id
   base_url = "http://192.0.2.30/"     # required; http or https; trailing slash is added
   timeout = 10.0                      # optional; seconds; default 10.0
   verify_tls = true                   # optional; default true; false skips HTTPS hostname and certificate checks
   driver = "http"                     # optional; default http; sim or http

messaging.redis
---------------

.. code-block:: toml

   [messaging.redis]
   redis_id = 1                        # required integer id
   host = "127.0.0.1"                  # required
   port = 6379                         # optional; default 6379
   db = 0                              # optional; default 0
   username = ""                       # optional; passed when set
   password = ""                       # optional; passed when set
   timeout = 10.0                      # optional; socket_timeout seconds; default 10.0
   driver = "redis"                    # optional; default redis; sim or redis

messaging.zmq
-------------

.. code-block:: toml

   [messaging.zmq]
   zmq_id = 1                          # required integer id
   endpoint = "tcp://127.0.0.1:5555"   # required
   socket = "pub"                      # required; pub or sub
   topic = ""                          # optional; default empty; SUB subscribes to this prefix
   mode = "bind"                       # optional; bind or connect; default bind for pub, connect for sub
   driver = "zmq"                      # optional; default zmq; sim or zmq

messaging.mqtt
--------------

.. code-block:: toml

   [messaging.mqtt]
   mqtt_id = 1                         # required integer id
   host = "127.0.0.1"                  # required
   port = 1883                         # optional; default 1883
   client_id = "colosseum-client"      # optional; default colosseum- plus 8 hex characters when empty
   username = ""                       # optional; username_pw_set when set
   password = ""                       # optional; sent with username when username is set
   topic = "#"                         # optional; default "#"; subscribe filter
   keepalive = 60                      # optional; seconds; default 60
   driver = "mqtt"                     # optional; default mqtt; sim or mqtt

messaging.ssh
-------------

.. code-block:: toml

   [messaging.ssh]
   ssh_id = 1                          # required integer id
   host = "192.0.2.40"                 # required
   username = "bench"                  # required
   port = 22                           # optional; default 22
   password = ""                       # optional; used when key_filename is empty
   key_filename = ""                   # optional; private key path; used instead of password when set
   timeout = 10.0                      # optional; seconds; default 10.0; bounds connect, banner, and auth
   driver = "ssh"                      # optional; default ssh; sim or ssh
   auth = "auto"                       # optional; default auto; auto accepts first-seen keys; none and auth_none require a trusted key
   platform = "linux"                  # optional; default linux when empty; linux or windows
   known_hosts = ""                    # optional path; omitted loads system host keys; auth auto creates a missing file
