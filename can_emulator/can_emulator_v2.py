import can
import time
import cantools

bus_type = 'socketcan'  # Change to 'virtual' for Windows/macOS
channel = 'vcan0'       # Change to 'test' for Windows/macOS
db = cantools.database.load_file("../test.dbc")

message = db.get_message_by_name("TEST_MSG")

bus = can.interface.Bus(bustype=bus_type, channel=channel, can_filters=None)

i = 0

while True:

    data = {
    "Mux": 0,
    "ResponseID": i,
    "TestValA": 100,   # example value
    "TestValB": 1,     # example value
    }

    encoded_data = message.encode(data)

    can_msg = can.Message(
        arbitration_id=message.frame_id,
        data=encoded_data,
        is_extended_id=False
    )

    try:
        bus.send(can_msg)
        print(f"Sent {message.name} with {data}")
    except can.CanError:
        print("Message NOT sent")

    i = i + 1

    if i == 16:
        i = 0

    time.sleep(1)
    
