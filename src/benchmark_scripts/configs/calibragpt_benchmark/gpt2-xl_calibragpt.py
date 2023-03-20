import json

with open("../../data/calibragpt_full_input_information.json", "r") as f:
    input_info = json.load(f)

config = {
    "models": [
        "gpt2-xl",
    ],
    "input_information": input_info,
    "verbosity": False,
}
