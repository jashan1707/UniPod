import pandas as pd
import glob
import os

# Define the path to the Parquet files
parquet_folder = os.path.expanduser("/Users/jashan.peiris/Downloads/risk_parquet_files")
parquet_files = glob.glob(os.path.join(parquet_folder, "*.parquet"))

if not parquet_files:
    print("No Parquet files found in the specified directory.")
    exit()

# Read and concatenate all Parquet files
df_list = [pd.read_parquet(file) for file in parquet_files]
combined_df = pd.concat(df_list, ignore_index=True)

# Define output CSV path
output_csv = os.path.join(parquet_folder, "combined_output.csv")

# Write to CSV
combined_df.to_csv(output_csv, index=False)

print(f"Combined CSV written to: {output_csv}")
