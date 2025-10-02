"""
Program: CAN Log Processor and Decoder
File: dbc_parser.py
Version: 1.0
Author: Farish Reheman
Date: July 8th, 2024
Description:
This program processes CAN (Controller Area Network) log files and decodes the messages
using a provided DBC (Database CAN) file. It converts the raw CAN log into a CSV format
and then decodes the messages based on the DBC specifications.
Usage:
python script_name.py <input_file> [--dbc <dbc_file>]
Change Log:
****************************************************************
|       Date       |       Change      |       Developer       |
****************************************************************
1. 07/08/2024         Initial Version       Farish Reheman
"""
import argparse
import csv
import re
from pathlib import Path

import cantools
import pandas as pd

def process_log_line(line):
    """
    Process a log line and extract relevant information.
    Args:
        line (str): The log line to process.
    Returns:
        tuple: A tuple containing the extracted information from the log line.
               The tuple contains the following elements:
               - Timestamp (str): The timestamp of the log line.
               - CAN bus (str): The CAN bus identifier.
               - Message ID (str): The ID of the message.
               - Message data (str): The data of the message.
               If the log line does not match the expected pattern, None is returned.
    """
    pattern = r'\(([\d.]+)\)\s+(can\d)\s+(\w+)#(\w+)'
    match = re.match(pattern, line)
    return match.groups() if match else None

def process_input_file(input_file, output_file):
    """
    Process the input file and write the parsed data to the output file in CSV format.
    Args:
        input_file (str): The path to the input file.
        output_file (str): The path to the output file.
    Returns:
        None
    """
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        csv_writer = csv.writer(outfile)
        csv_writer.writerow(['Timestamp', 'CAN_Ch', 'ID_HEX', 'DATA'])
       
        for line in infile:
            result = process_log_line(line.strip())
            if result:
                csv_writer.writerow(result)

def decode_can_messages(db, df, decoded_file):
    """
    Decodes CAN messages using a DBC file and writes the decoded information to a CSV file.
    Parameters:
    - db (DBC): The DBC object containing the message and signal definitions.
    - df (DataFrame): The DataFrame containing the CAN messages to be decoded.
    - decoded_file (str): The path to the output CSV file.
    Returns:
    - error_occurred (bool): True if an error occurred during decoding, False otherwise.
    """
    header = ['TIMESTAMP','ID_HEX','XRCC','Battery','Signal Name','Value','Comments']
    error_occurred = False

    with open(decoded_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(header)

        for row in df.itertuples(index=True, name='Pandas'):
       
            idhex = int(row.ID_HEX, 16)
            batt_num = idhex & 0x007        # Extracting the last 3 bits for battery number
            xrcc_num = ((idhex >> 3) & 0xF) # Extracting bits 7 to 4 for XRCC number
            cmd = idhex & 0xF80             # Extracting 4 MSB bits
           
            try:
                decoded = db.decode_message(idhex, bytes.fromhex(row.DATA))
               
                # For populating the message information
                writer.writerow([float(row.Timestamp), row.ID_HEX, "NA", "NA", db.get_message_by_frame_id(idhex).name,"", db.get_message_by_frame_id(idhex).comment])
               
                # For populating the signal information
                for key, value in decoded.items():  
                    writer.writerow(["","","","", key,value,db.get_message_by_frame_id(idhex).get_signal_by_name(key).comment])
               
            except KeyError:
                # This section decodes xrcc/battery specific information using addressing
                try:
                    decoded = db.decode_message(cmd, bytes.fromhex(row.DATA))
                    writer.writerow([float(row.Timestamp), row.ID_HEX, xrcc_num, batt_num, db.get_message_by_frame_id(cmd).name,"", db.get_message_by_frame_id(cmd).comment])
                    for key, value in decoded.items():  
                        writer.writerow(["","","","", key,value,db.get_message_by_frame_id(cmd).get_signal_by_name(key).comment])

                except KeyError:
                    # Message not found in DBC file
                    writer.writerow([row.Timestamp, row.ID_HEX,"","","UNKNOWN DATA"])
                    error_occurred = True

    return error_occurred

def main():
    parser = argparse.ArgumentParser(description='Process CAN log file and map with DBC file.')
    parser.add_argument('input_file', help='Input CAN log file name')
    parser.add_argument('--dbc', help='DBC file name (default: test.dbc)')
    args = parser.parse_args()

    input_file = Path(args.input_file)
    output_file = input_file.with_name('processed_can_log.csv')
    decoded_file = input_file.with_name('decoded_log.csv')

    process_input_file(input_file, output_file)
    print(f"Processing complete. Results saved to {output_file}. Loading DBC file.")

    df = pd.read_csv(output_file, dtype=str)
    db = cantools.database.load_file(args.dbc)

    error_occurred = decode_can_messages(db, df, decoded_file)

    if error_occurred:
        print("Mapping completed with Errors!")
    else:
        print("Mapping Complete. Generated CSV file.")

if __name__ == "__main__":
    main()