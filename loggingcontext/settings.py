config = dict(
    stomp_handler=dict(
        host_and_ports=[('localhost', 61613),
                        ],
        keepalive=True,
        user='guest',
        passcode='guest',
    ),
    max_queue=100
)
