config = dict(
    # stomp_handler=dict(
    #     connection=dict(
    #         host_and_ports=[# ('localhost', 61613),
    #                         ],
    #         keepalive=True,
    #         user='guest',
    #         passcode='guest',
    #     ),
    #     max_queue=100,
    #     connect_timeout=3,
    #     sleep=0.1,
    # ),
    amqp_handler=dict(
        url='amqp://guest:guest@localhost:5672/%2F',
        exchange='lc-topic',
        exchange_type='topic'
    ),
)
