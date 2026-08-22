import os

for dataset in ["ten_k", "ectsum", "kleister_nda"]:
    path = f"data/{dataset}"
    print(f"\n=== {dataset} ===")
    if not os.path.exists(path):
        print("  FOLDER DOES NOT EXIST")
        continue
    for root, dirs, files in os.walk(path):
        level = root.replace(path, "").count(os.sep)
        indent = "  " * level
        print(f"{indent}{os.path.basename(root)}/")
        if level < 3:  # only show 3 levels deep
            for f in files[:10]:  # first 10 files
                print(f"{indent}  {f}")
            if len(files) > 10:
                print(f"{indent}  ... and {len(files)-10} more files")
