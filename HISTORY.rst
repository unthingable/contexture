.. :changelog:

History
-------

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
