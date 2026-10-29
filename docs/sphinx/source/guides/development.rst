Messaging implementation notes
==============================

The public protocol wrappers own client caching and listener lifetime. Their
private ``_pump`` module is an implementation detail, not a stable extension
API. Contributor experiments can use it, but user tests should call the public
``listen`` and ``stop_listen`` APIs. Internal imports can change with the package.

``MessagePump`` is that same loop for a poll callable the wrappers do not
cover. It does not write the database; pass an ``on_message`` that does::

   from colosseum_messaging._pump import MessagePump

   pump = MessagePump(poll=my_poll, on_message=my_handler, name="custom-listen")
   pump.start()
   pump.stop()


Run ``python -m pytest`` from the repository root after changes. The standard
install includes the driver and test dependencies; see the README for setup.
