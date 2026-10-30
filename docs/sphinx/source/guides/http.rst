HTTP requests and responses
===========================

``get``, ``post``, ``put``, ``delete`` and ``request`` return
``{"status_code": int, "body": str}``; ``body`` is decoded text, not parsed JSON.
``json=`` serializes a request body and supplies Content-Type unless overridden;
``data=`` supplies raw bytes/text instead. ``headers=`` and ``timeout=`` are
per-call arguments. The example POST includes all three.

For live HTTP, omit ``driver="sim"`` and configure::

   [messaging.http]
   http_id = 1
   base_url = "https://device.example/"
   timeout = 5.0
   verify_tls = true

Use ``verify_status`` and ``verify_body_match`` with the measurement key. An
HTTP error status is still a response to verify; transport failures raise an
error. A request timeout limits network operations, not a product's eventual
business completion. HTTP uses stdlib ``http.client``.


In a CLI-managed ``main()`` with the HTTP row above loaded::

   col.messaging.http.get(http_id=1, path="/health", key="health")
   col.messaging.http.verify_status(key="health", expected=200)
   col.messaging.http.verify_body_match(key="health", pattern=r"ready")

Adapt the endpoint and response contract to your server. A completed HTTP 500
is stored response evidence; a required status check against 200 records FAIL.
A refused connection or transport timeout is a measurement ERROR and normally
re-raises. See :doc:`/api/http`, :doc:`/config_reference`, and
:doc:`protocol_workflows` for the offline example and failure categories.
