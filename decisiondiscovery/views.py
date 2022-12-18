from asyncore import write
from typing import List
import pandas as pd
import os
import time
import shutil
import graphviz
import matplotlib.image as plt_img
import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_graphviz, export_text
import matplotlib.pyplot as plt
from sklearn.metrics import accuracy_score
from chefboost import Chefboost as chef
from art import tprint
from rim.settings import sep, decision_foldername, platform_name, flattening_phase_name, decision_model_discovery_phase_name
from .decision_trees import CART_sklearn_decision_tree, chefboost_decision_tree
from .flattening import flat_dataset_row
# import json
# import sys
# from django.shortcuts import render
# import seaborn as sns
# from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

# def clean_dataset(df):
#     assert isinstance(df, pd.DataFrame), "df needs to be a pd.DataFrame"
#     df.dropna(inplace=True)
#     indices_to_keep = ~df.isin([np.nan, np.inf, -np.inf]).any(1)
#     return df[indices_to_keep].astype(np.float64)


def extract_training_dataset(decision_point_activity,
        target_label,
        special_colnames,
        columns_to_drop,
        log_path="media/enriched_log_feature_extracted.csv", 
        path_dataset_saved="media/", 
        actions_columns=["Coor_X", "Coor_Y", "MorKeyb", "TextInput", "Click"]):
    """
    Iterate for every UI log row:
        For each case:
            Store in a map all the attributes of the activities until reaching the decision point
            Assuming the decision point is on activity D, the map would have the following structure:
        {
            "headers": ["timestamp", "MOUSE", "clipboard"...],
            "case1": {"CoorX_A": "value1", "CoorY_A": "value2", ..., "Checkbox_A: "value3",
                        "CoorX_B": "value1", "CoorY_B": "value2", ..., "Checkbox_B: "value3"
                        "CoorX_C": "value1", "CoorY_C": "value2", ..., "Checkbox_C: "value3"
                },
            ...
            
            "caseN": {"CoorX_A": "value1", "CoorY_A": "value2", ..., "Checkbox_A: "value3",
                        "CoorX_B": "value1", "CoorY_B": "value2", ..., "Checkbox_B: "value3"
                        "CoorX_C": "value1", "CoorY_C": "value2", ..., "Checkbox_C: "value3"
                },
        }

    Once the map is generated, for each case, we concatinate the header with the activity to name the columns and assign them the values
    For each case a new row in the dataframe is generated
    
    :param decision_point_activity: id of the activity inmediatly previous to the decision point which "why" wants to be discovered
    :type decision_point_activity: str
    :param target_label: name of the column where classification target label is stored
    :type target_label: str
    :param special_colnames: dict that contains the column names that refers to special columns: "Screenshot", "Variant", "Case"...
    :type special_colnames: dict
    :param columns_to_drop: Names of the colums to remove from the dataset
    :type columns_to_drop: list
    :param log_path: path where ui log to be processed is stored
    :type log_path: str
    :param path_dataset_saved: path where files that results from the flattening are stored
    :type path_dataset_saved: str
    :param actions_columns: list that contains column names that wont be added to the event information just before the decision point
    :type actions_columns: list
    """
    tprint(platform_name + " - " + flattening_phase_name, "fancy60")
    print(log_path+"\n")

    log = pd.read_csv(log_path, sep=",", index_col=0)

    # columns_to_drop = [special_colnames["Case"], special_colnames["Activity"], special_colnames["Timestamp"], special_colnames["Screenshot"], special_colnames["Variant"]]
    columns = list(log.columns)
    for c in columns_to_drop:
        columns.remove(c)
        
    # Stablish common columns and the rest of the columns are concatinated with "_" + activity
    flat_dataset_row(log, columns, target_label, path_dataset_saved, special_colnames["Case"], special_colnames["Activity"], 
                     special_colnames["Timestamp"], decision_point_activity, actions_columns)

                     
def decision_tree_training(param_preprocessed_log_path="media/preprocessed_dataset.csv",
                           param_path="media/", 
                           implementation="sklearn",
                           algorithms=['ID3', 'CART', 'CHAID', 'C4.5'],
                           columns_to_ignore=["Timestamp_start", "Timestamp_end"],
                           target_label='Variant',
                           one_hot_columns=['NameApp']):
    
    tprint(platform_name + " - " + decision_model_discovery_phase_name, "fancy60")
    print(param_preprocessed_log_path+"\n")
    
    flattened_dataset = pd.read_csv(param_preprocessed_log_path, index_col=0, sep=',')
    param_path += decision_foldername + sep
    if not os.path.exists(param_path):
        os.mkdir(param_path)
    one_hot_cols = []
    for c in flattened_dataset.columns:
        for item in one_hot_columns:
            if item in c:
                one_hot_cols.append(item)
        
        # if "TextInput" in c:
        #     columns_to_ignore.append(c)  # TODO: get type of field using NLP: convert to categorical variable (conversation, name, email, number, date, etc)
            
    flattened_dataset = pd.get_dummies(flattened_dataset, columns=one_hot_cols)
    flattened_dataset = flattened_dataset.drop(columns_to_ignore, axis=1)
    flattened_dataset = flattened_dataset.fillna(0.)
    # Splitting dataset
    # X_train, X_test = train_test_split(flattened_dataset, test_size=0.2, random_state=42, stratify=flattened_dataset[target_label])
    
    
    if implementation == 'sklearn':
        return CART_sklearn_decision_tree(flattened_dataset, param_path, target_label)
    else:
        return chefboost_decision_tree(flattened_dataset, param_path, algorithms)

def decision_tree_predict(module_path, instance):
    """
    moduleName = "outputs/rules/rules" #this will load outputs/rules/rules.py
    instance = for example ['Sunny', 'Hot', 'High', 'Weak']
    """
    tree = chef.restoreTree(module_path)
    prediction = tree.findDecision(instance)
    return prediction