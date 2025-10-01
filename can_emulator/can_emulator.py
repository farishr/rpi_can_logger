import can
import time
import random

# --- Configuration ---
# Set up the virtual CAN bus.
# On Linux, use 'socketcan' with 'vcan0'.
# On Windows/macOS, use the built-in 'virtual' interface.
bus_type = 'socketcan'  # Change to 'virtual' for Windows/macOS
channel = 'vcan0'       # Change to 'test' for Windows/macOS

# CAN message details for the sensor data
SENSOR_ID = 0x123      # The arbitration ID for the sensor
DATA_LENGTH = 8        # A standard CAN message has 8 bytes of data

def generate_sensor_data():
    """Generates a list of simulated sensor data."""
    # Create a random temperature value
    temperature_celsius = random.uniform(20.0, 30.0)
    
    # Pack the temperature value into bytes.
    # For this example, we'll send it as a 2-byte integer representing
    # the value scaled by 100 to preserve precision.
    packed_data = int(temperature_celsius * 100).to_bytes(2, 'big')
    
    # Pad the rest of the message with zeros
    return list(packed_data) + [0] * (DATA_LENGTH - 2)

def sensor_emulator():
    """
    Creates a virtual sensor that sends temperature data to a CAN bus.
    """
    print(f"Creating a CAN bus connection on {bus_type} with channel {channel}...")
    try:
        # Create a CAN bus instance
        bus = can.interface.Bus(bustype=bus_type, channel=channel, can_filters=None)
        print("Sensor emulator connected to the bus.")
    except can.CanError as e:
        print(f"Failed to connect to the CAN bus: {e}")
        return

    try:
        while True:
            # Generate new data
            data = generate_sensor_data()
            
            # Create a CAN message
            message = can.Message(
                arbitration_id=SENSOR_ID,
                data=data,
                is_extended_id=False
            )
            
            # Send the message
            bus.send(message)
            print(f"Sent message with ID 0x{SENSOR_ID:X}, Data: {data}")
            
            # Wait for a brief period before sending the next message
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping sensor emulator.")
    finally:
        bus.shutdown()
        print("Bus shut down.")

if __name__ == "__main__":
    sensor_emulator()

