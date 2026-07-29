from datasets import load_dataset

print("Downloading DocVQA dataset...")

ds = load_dataset("VLR-CVC/DocVQA-2026")

print(ds)