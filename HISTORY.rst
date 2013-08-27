.. :changelog:

History
-------

0.10.3 (2013-08-08)
+++++++++++++++++++
- Fix objects() iterator

0.10.2 (2013-08-07)
+++++++++++++++++++
- configure() now takes parameters in addition to URL string.

0.10.1 (2013-08-06)
+++++++++++++++++++
- A new ``format`` argument for Context._update(). When ``False`` it will not attempt to process curly braces by calling .format() on the message string.

0.10.0 (2013-08-01)
+++++++++++++++++++
- Add non-logging based configuration (context.configure()), to get around logger hijacking (I'm looking at you, celery)
- Context processor can now wait for the handler queue to empty, automatically. This simplifies things for short-running process and guarantees EOL message delivery.

0.9.9 (2013-06-27)
+++++++++++++++++

- Keep messages until channel is open
- monitor: add queue declare args

``lcmon``:

- ``--keys``: will now stay in order
- Add ``--trim``
- Add ``-z``
- Add version to help
- Add tests

0.9.8 (2013-06-05)
+++++++++++++++++

- Add missing config.conf to MANIFEST.in
- Deal with variable args in AMQP callbacks

0.9.6 (2013-06-03)
+++++++++++++++++

- Add thread id to handler announcement
- Add reconnection timeout argument to amqp_handler
- Add amqp_handler tests
- Bump pika version to 0.9.13

0.9.5 (2013-05-23)
++++++++++++++++++

- Announce queue overflows to the bus (from AMQPHandler's own context)
- Announce queue overflows on threshold crossings only (instead of every message)
- Publisher thread and queue are now singletons (configurable)
- Add AMQPHandler arguments for max queue lenght and singularity

0.9.4 (2013-05-17)
++++++++++++++++++

- Fix ``on_connection_closed()`` signature, no more exceptions
- Move ``__version__`` to ``__init__.py`` where it belongs

0.9.3 (2013-04-28)
++++++++++++++++++

- Fix time format

0.9.2 (2013-04-03)
++++++++++++++++++

- Reconnect to AMQP endpoint on all connection exceptions
