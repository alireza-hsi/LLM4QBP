import os
import openpyxl
import pandas as pd
import re

# output experience all valuegain into .xlsx
# mmm log dir
diectory_dataset = "./mmm/logs"
# excel dir
excel_file = "output.xlsx"  
wb = openpyxl.load_workbook(excel_file)
ws = wb.active
for logroot,directoryList,files in os.walk(diectory_dataset):
    for directory in directoryList:
        directory = os.path.join(diectory_dataset,directory)
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".log"):  
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        info = []
                        file_contents = f.read()
                        regex = r"log_filename:([\w\d]*).log"
                        matches = re.finditer(regex, file_contents, re.DOTALL)
                        for match in matches:
                            print(match.group(1))
                            info.append(match.group(1))
                            break
                        new_row_data = []  
                        # regex_num = r"valueGain=([\d.]*)"
                        # info.append("valueGain")
                        # matches = re.finditer(regex_num, file_contents, re.DOTALL)
                        # for match in matches:
                        #     print(match.group(1))
                        #     info.append(match.group(1))
                        regex_node = r"(\d*) Node"
                        info.append("Node")
                        matches = re.finditer(regex_node, file_contents, re.DOTALL)
                        for match in matches:
                            if match.group(1) !=" " and  match.group(1) !="":
                                info.append(match.group(1))
                                print(match.group(1))

                        regex_node = r"(\d*) Edge"
                        info.append("Edge")
                        matches = re.finditer(regex_node, file_contents, re.DOTALL)
                        for match in matches:
                            if match.group(1) != " " and match.group(1) !="":
                                info.append(match.group(1))
                                print(match.group(1))

                        ws.append(info)
                    f.close()

wb.save("output.xlsx")

wb.close()