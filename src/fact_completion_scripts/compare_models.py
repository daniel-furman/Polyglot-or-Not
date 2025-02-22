"""
Wrapper helpers for running fact completion with contrastive knowledge assessment
"""

import datetime
import json
import os
import numpy as np
import tqdm
import torch

import transformers
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    AutoModelForMaskedLM,
    AutoModelForSeq2SeqLM,
)

from probe_helpers import (
    probe_gpt,
    probe_bert,
    probe_llama,
    probe_t5,
    probe_stablelm,
    probe_mpt,
    probe_redpajama,
    probe_falcon,
)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
if not torch.cuda.is_available():
    raise Exception("Change runtime type to include a GPU.")


# first, write helper to pull a pretrained LM and tokenizer off the shelf
def get_model_and_tokenizer(model_name):
    if "t5" in model_name.lower():
        return AutoTokenizer.from_pretrained(
            model_name
        ), AutoModelForSeq2SeqLM.from_pretrained(
            model_name, load_in_8bit=True, device_map="auto", torch_dtype=torch.float16
        )

    elif (
        ("gpt" in model_name.lower())
        or ("opt" in model_name.lower())
        or ("pythia" in model_name.lower())
        or ("bloom" in model_name.lower())
    ):
        return AutoTokenizer.from_pretrained(
            model_name
        ), AutoModelForCausalLM.from_pretrained(
            model_name, load_in_8bit=True, device_map="auto", torch_dtype=torch.float16
        )

    elif ("stablelm" in model_name.lower()) or ("redpajama" in model_name.lower()):
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        tokenizer.pad_token = "<|padding|>"
        return tokenizer, AutoModelForCausalLM.from_pretrained(
            model_name, load_in_8bit=True, device_map="auto", torch_dtype=torch.float16
        )

    elif "mpt" in model_name.lower():
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        tokenizer.pad_token = "<|padding|>"

        bnb_config = transformers.BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=bnb_config,
            device_map={"": 0},
            # torch_dtype=torch.float16,
            trust_remote_code=True,
        )  # .to(device)

        return (
            tokenizer,
            model,
        )

    elif "bert" in model_name.lower():
        return AutoTokenizer.from_pretrained(
            model_name
        ), AutoModelForMaskedLM.from_pretrained(
            model_name, torch_dtype=torch.float16
        ).to(
            device
        )

    elif "llama" in model_name.lower():
        tokenizer = transformers.AutoTokenizer.from_pretrained(model_name)
        tokenizer.pad_token = tokenizer.eos_token

        model = transformers.LlamaForCausalLM.from_pretrained(
            model_name, load_in_8bit=True, device_map="auto", torch_dtype=torch.float16
        )
        return tokenizer, model

    elif "mistral" in model_name.lower():
        tokenizer = transformers.AutoTokenizer.from_pretrained(model_name)
        tokenizer.pad_token = tokenizer.eos_token

        model = transformers.AutoModelForCausalLM.from_pretrained(
            model_name, load_in_8bit=True, device_map="auto", torch_dtype=torch.float16
        )
        return tokenizer, model

    elif "falcon" in model_name.lower():
        tokenizer = transformers.AutoTokenizer.from_pretrained(model_name)
        tokenizer.pad_token = tokenizer.eos_token

        bnb_config = transformers.BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=bnb_config,
            device_map="auto",
            # torch_dtype=torch.float16,
            trust_remote_code=True,
        )  # .to(device)

        return (
            tokenizer,
            model,
        )


# next, write a helper to pull a probe function for the given LM
def get_probe_function(prefix):
    probe_functions = [
        probe_gpt,
        probe_bert,
        probe_llama,
        probe_t5,
        probe_stablelm,
        probe_mpt,
        probe_redpajama,
        probe_falcon,
    ]
    for func in probe_functions:
        if prefix.lower() in func.__name__:
            return func


# lastly, write a wrapper function to compare models
def compare_models(model_name_list, input_dataset, verbose):
    """
    Model-wise comparison helper function
    """

    print("Made it to start of compare models")

    score_dict_full = {}
    score_dict_summary = {}
    itr_run_babysitting = 0
    list_run_babysitting = list(np.arange(0, 26300, 1000))

    if not os.path.isdir("logging"):
        os.mkdir("logging")

    now = datetime.datetime.now()
    dt_string = now.strftime("%d-%m-%Y-%H-%M-%S")

    for model_name in model_name_list:
        true_count = 0
        fact_count = 0
        p_falses = []
        p_trues = []

        print(f"CKA for {model_name}")
        print("Loading  model...")

        # get proper model and tokenizer
        tokenizer, model = get_model_and_tokenizer(model_name)

        print("Running comparisons...")

        # establish prefix
        prefix = ""
        probe_func = None

        # get correct CKA function
        if "t5" in model_name.lower():
            prefix = "t5"
            probe_func = get_probe_function(prefix)
        elif (
            ("gpt-neo" in model_name.lower())
            or ("gpt-j" in model_name.lower())
            or ("pythia" in model_name.lower())
        ):
            prefix = "eleutherai"
            probe_func = get_probe_function("gpt")

        elif "gpt" in model_name.lower():
            prefix = "gpt"
            probe_func = get_probe_function(prefix)

        elif "opt" in model_name.lower():
            prefix = "opt"
            probe_func = get_probe_function("gpt")

        elif "roberta" in model_name.lower():
            prefix = "roberta"
            probe_func = get_probe_function("bert")

        elif "bert" in model_name.lower():
            prefix = "bert"
            probe_func = get_probe_function(prefix)

        elif "llama" in model_name.lower():
            prefix = "llama"
            probe_func = get_probe_function(prefix)

        elif "mistral" in model_name.lower():
            prefix = "mistral"
            probe_func = get_probe_function("llama")

        elif "bloom" in model_name.lower():
            prefix = "bloom"
            probe_func = get_probe_function("gpt")

        elif "stablelm" in model_name.lower():
            prefix = "stablelm"
            probe_func = get_probe_function(prefix)

        elif "mpt" in model_name.lower():
            prefix = "mpt"
            probe_func = get_probe_function(prefix)

        elif "redpajama" in model_name.lower():
            prefix = "redpajama"
            probe_func = get_probe_function(prefix)

        elif "falcon" in model_name.lower():
            prefix = "falcon"
            probe_func = get_probe_function(prefix)

        # iterate over context/entity pairings
        # input_dataset is a datasets dataset
        # context is a plain string (since our context's will be unique)
        # and entities is a list containing, in the first slot, the true
        # value for the statement and in the subsequent slots, incorrect information
        for entities_dict in tqdm.tqdm(input_dataset):
            # convert string of list into a real list
            if " <br> " in entities_dict["false"]:
                counterfacts_list = entities_dict["false"].split(" <br> ")
            else:
                counterfacts_list = [entities_dict["false"]]

            # intitiate vars
            p_true = 0.0
            p_false = 0.0
            p_false_list_inner = []

            # grab true and false entities
            entities = [entities_dict["true"]]
            entities.extend(counterfacts_list)

            # iterate through each fact and counterfact
            for entity_count, entity in enumerate(entities):
                # grab the context
                context = entities_dict["stem"]
                # if multiple stems are stored, grab the correct one
                # (zeroeth stem is true fact, next ones are counterfacts)
                if " <br> " in context:
                    context = context.split(" <br> ")
                if type(context) == list:
                    context = context[entity_count]
                # necessary additions based on model type
                if prefix == "roberta":
                    context += " <mask>."
                elif prefix == "bert":
                    context += " [MASK]."

                # first find target vocab id
                # default to the very first token that get's predicted
                # e.g. in the case of Tokyo, which gets split into <Tok> <yo>,
                target_id = None
                if prefix == "t5":
                    target_ids = tokenizer.encode(
                        " " + entity,
                        padding="longest",
                        max_length=512,
                        truncation=True,
                        return_tensors="pt",
                    ).tolist()
                    space_only_token = tokenizer.encode(" ")[0]
                    try:
                        target_ids[0].remove(space_only_token)
                    except ValueError:
                        pass
                    target_id = torch.tensor(target_ids).to(device)[0][0]

                elif (
                    (prefix == "gpt")
                    or (prefix == "eleutherai")
                    or (prefix == "bloom")
                    or (prefix == "stablelm")
                    or (prefix == "mpt")
                    or (prefix == "redpajama")
                ):
                    target_id = tokenizer.encode(" " + entity, return_tensors="pt").to(
                        device
                    )[0][0]

                elif prefix == "falcon":
                    target_id = tokenizer.encode(
                        " " + entity, return_token_type_ids=False, return_tensors="pt"
                    ).to(device)[0][0]

                elif prefix == "opt":
                    target_id = tokenizer.encode(" " + entity, return_tensors="pt").to(
                        device
                    )[0][1]

                elif prefix == "roberta":
                    target_id = tokenizer.encode(
                        " " + entity,
                        padding="longest",
                        max_length=512,
                        truncation=True,
                        return_tensors="pt",
                    ).to(device)[0][1]

                elif prefix == "bert":
                    target_id = tokenizer.encode(
                        entity,
                        padding="longest",
                        max_length=512,
                        truncation=True,
                        return_tensors="pt",
                    ).to(device)[0][1]

                elif (prefix == "llama") or (prefix == "mistral"):
                    target_id = tokenizer.encode(" " + entity, return_tensors="pt").to(
                        device
                    )[0][2]

                # next call probe function
                model_prob = probe_func(model, tokenizer, target_id, context, verbose)

                # lastly, register results
                # if it is the first time through, it is the fact
                if entity_count == 0:
                    p_true = model_prob
                # if it is the second+ time through, it is the counterfactual(s)
                else:
                    p_false += model_prob
                    p_false_list_inner.append(float(model_prob))

            # entity count is equal to the num counterfactuals
            # (since it started at a 0 index in the enumerate)
            p_false /= entity_count

            # record results:
            score_dict_full_data = {
                "stem": context,
                "fact": entities[0],
                "counterfact": entities[1:],
                "p_true": float(p_true),
                "p_false_list": p_false_list_inner,
                "p_false_average": float(p_false),
                "p_true / p_false_average": np.round(
                    float(p_true) / (float(p_false) + 1e-13), decimals=4
                ),
                "p_true > p_false_average": str(float(p_true) > float(p_false)),
            }

            # record the rest of the metadata
            try:
                score_dict_full_data["subject"] = entities_dict["subject"]
            except KeyError:
                pass
            try:
                score_dict_full_data["object"] = entities_dict["object"]
            except KeyError:
                pass
            try:
                score_dict_full_data["relation"] = entities_dict["relation"]
            except KeyError:
                pass
            try:
                score_dict_full_data["dataset_id"] = entities_dict["dataset_id"]
            except KeyError:
                pass

            # add results to the given model name
            try:
                score_dict_full[model_name.lower()].append(score_dict_full_data)
            except KeyError:
                score_dict_full[model_name.lower()] = [score_dict_full_data]

            # append p_false and p_true
            p_falses.append(float(p_false))
            p_trues.append(float(p_true))

            # update counts based on probs
            if p_true > p_false:
                true_count += 1
            fact_count += 1

            # randomly print some during training to checkin on thing
            if itr_run_babysitting in list_run_babysitting:
                print(
                    f"\nRandom prints, itr {itr_run_babysitting}: \n\t{score_dict_full_data}"
                )
            itr_run_babysitting += 1

        # record the summary dict
        score_dict_summary[
            model_name.lower()
        ] = f"This model predicted {true_count}/{fact_count} facts at a higher prob than the given counterfactual. In addition, the mean p_true was {np.round(np.mean(np.array(p_trues)), decimals=4)} while the mean p_false_average was {np.round(np.mean(np.array(p_falses)), decimals=4)}."

        print("Done\n")
        del tokenizer
        del model
        torch.cuda.empty_cache()

    score_dicts = [score_dict_full, score_dict_summary]

    # logging
    score_dicts_logging = {}
    score_dicts_logging["curr_datetime"] = str(now)
    try:
        score_dicts_logging["model_name"].append(model_name)
    except KeyError:
        score_dicts_logging["model_name"] = [model_name]

    score_dicts_logging["score_dict_summary"] = score_dict_summary
    score_dicts_logging["score_dict_full"] = score_dict_full

    log_fpath = f"logging/{prefix}-logged-cka-outputs-{dt_string}.json"

    with open(log_fpath, "w") as outfile:
        json.dump(score_dicts_logging, outfile)

    return score_dicts, log_fpath
