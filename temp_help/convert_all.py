import sys
import os
import subprocess

if __name__ == "__main__":
    args = sys.argv[1:]

    if args[0].lower() == "--core":
        subprocess.run(["python", "./help_convert.py", "--get-all-mods"])

        module_names = []
        with open("mod.txt", "r") as f:
            for line in f:
                module_names.append(f.readline())

        with open(os.devnull, 'w') as devnull: # silence stdout by redirecting to devnull
            for mod in module_names:
                args = ["python", "./help_convert.py", mod, "--test"]
                subprocess.run(args, stdout=devnull)

    elif args[0].lower() == "--extensions":
        pass
