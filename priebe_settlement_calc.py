#!/usr/bin/env python3
"""
Priebe Stone Column Settlement Calculator
------------------------------------------
Calculates primary settlement with and without stone column improvement.

Untreated stress methods:  Boussinesq | 2:1 (2V:1H) | Westergaard

Treated stress methods:
  • 4:1→2:1  — 4V:1H from BOF to 2/3 SC length, then 2V:1H below  (Priebe default)
  • Boussinesq
  • Westergaard

Improvement (within SC zone):
    ΔS_treated = (Δσ_treated / Em_s) × h × (s/s∞) / n
    n  = 1 + ar*(K-1)         [composite-modulus improvement factor]
    s/s∞ = bilinear interpolation from Priebe depth-distribution table
           row = ar × z_into_SC_bottom,  column = n

Usage:  python priebe_settlement_calc.py
"""

import sys
import math
import json
import os
from dataclasses import dataclass, field
from typing import List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTabWidget, QFormLayout, QGroupBox, QLabel, QLineEdit, QDoubleSpinBox,
    QSpinBox, QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QMessageBox, QAbstractItemView, QStatusBar,
    QFrame, QSizePolicy, QGridLayout, QScrollArea, QFileDialog, QInputDialog,
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QColor, QFont

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import numpy as np


# ═══════════════════════════════════════════════════════════════════
# PRIEBE s/s∞ DEPTH-DISTRIBUTION TABLE  (from Priebe 1995 / Vibro-Replacement)
# ═══════════════════════════════════════════════════════════════════
# Row axis: y = ar × z_into_SC  (area-ratio × depth below SC top, 0 → 32 step 0.5)
# Col axis: n = improvement factor  (1, 2, 3, … 40)
# Values:   s/s∞  (fraction of total SC-length settlement achieved at depth y)
#
# Usage: row  = ar × z_into_SC_bottom
#        col  = n2 = 1 + ar*(Em_sc/Em_s - 1)   [composite modulus factor]
#        s/s∞ = bilinear_interp(PRIEBE_TABLE, row, col)
#        ΔS_treated = (Δσ/Em_s) × h × s/s∞ / n2

_P_N = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 35, 40]
_P_Y = [y * 0.5 for y in range(65)]   # 0.0, 0.5, 1.0, …, 32.0

_P_TABLE = [
 [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
 [0.9319,0.9471,0.9554,0.9634,0.9683,0.9724,0.9758,0.9781,0.9798,0.9819,0.9858,0.9884,0.9907,0.9925,0.9938,0.9946],
 [0.8612,0.8937,0.9109,0.9268,0.9366,0.9448,0.9515,0.9562,0.9597,0.9638,0.9716,0.9769,0.9814,0.9849,0.9877,0.9892],
 [0.7877,0.8363,0.8645,0.8892,0.9049,0.9173,0.9273,0.9343,0.9395,0.9456,0.9573,0.9653,0.9721,0.9774,0.9815,0.9838],
 [0.7124,0.7793,0.8173,0.8491,0.8722,0.89,0.903,0.9124,0.9193,0.9275,0.9431,0.9538,0.9628,0.9699,0.9753,0.9784],
 [0.64,0.7232,0.7723,0.8131,0.8419,0.8634,0.8793,0.8909,0.8992,0.9095,0.9289,0.9422,0.9536,0.9623,0.9691,0.973],
 [0.5732,0.6713,0.7285,0.7778,0.8116,0.8379,0.8557,0.8698,0.8805,0.8918,0.9147,0.9307,0.9443,0.9548,0.963,0.9676],
 [0.5132,0.6223,0.6871,0.743,0.7814,0.8125,0.8328,0.8486,0.8617,0.8742,0.9017,0.9195,0.9353,0.9478,0.9568,0.9622],
 [0.4604,0.5797,0.6506,0.7125,0.7519,0.788,0.8102,0.8277,0.8438,0.8571,0.889,0.9092,0.9267,0.9412,0.9506,0.9568],
 [0.4178,0.5433,0.6186,0.6836,0.7283,0.7644,0.7906,0.8104,0.8263,0.8407,0.8762,0.8988,0.9181,0.9347,0.9444,0.9514],
 [0.3846,0.5068,0.5883,0.6569,0.7051,0.7437,0.7719,0.7932,0.8094,0.8257,0.8634,0.8885,0.9096,0.9281,0.9385,0.9463],
 [0.3551,0.4772,0.5612,0.6312,0.683,0.7236,0.7533,0.7762,0.794,0.811,0.8506,0.8788,0.9019,0.9216,0.9327,0.9412],
 [0.3319,0.451,0.5353,0.6073,0.6622,0.7039,0.7353,0.7599,0.7788,0.7965,0.8394,0.8696,0.8942,0.9152,0.9269,0.9362],
 [0.3114,0.4298,0.5148,0.5853,0.6419,0.6844,0.7173,0.7438,0.764,0.782,0.8287,0.8605,0.8865,0.9089,0.9212,0.9311],
 [0.292,0.4089,0.4943,0.5644,0.623,0.6657,0.7007,0.7292,0.7494,0.7687,0.818,0.8513,0.8788,0.9025,0.9158,0.9262],
 [0.2747,0.3883,0.4747,0.5463,0.6045,0.6486,0.6845,0.7146,0.7354,0.7556,0.8073,0.8422,0.8717,0.8961,0.9104,0.9213],
 [0.2582,0.37,0.4559,0.5284,0.5876,0.632,0.6683,0.6997,0.7217,0.7428,0.7966,0.8337,0.8646,0.8897,0.905,0.9164],
 [0.2434,0.3525,0.4396,0.5108,0.5708,0.6159,0.6534,0.6845,0.7088,0.7307,0.7859,0.8254,0.8575,0.8833,0.8997,0.9115],
 [0.2303,0.3381,0.4246,0.4957,0.5548,0.5998,0.6392,0.6693,0.696,0.7186,0.7752,0.817,0.8505,0.8769,0.8943,0.9066],
 [0.2174,0.325,0.4109,0.4812,0.5403,0.5851,0.6251,0.655,0.6831,0.7073,0.7644,0.8086,0.8437,0.8704,0.8889,0.9016],
 [0.2086,0.3129,0.3986,0.4683,0.5268,0.5715,0.6107,0.6411,0.6702,0.6962,0.7539,0.8003,0.837,0.8645,0.8832,0.8966],
 [0.1997,0.3035,0.3869,0.4559,0.5136,0.5575,0.5962,0.6272,0.6574,0.6851,0.7437,0.792,0.8302,0.8585,0.8775,0.8916],
 [0.1909,0.294,0.3758,0.4436,0.5006,0.5431,0.5817,0.6139,0.6448,0.6742,0.7335,0.7846,0.8234,0.8525,0.8718,0.8866],
 [0.1829,0.2847,0.3647,0.4315,0.4877,0.5293,0.5691,0.6017,0.6334,0.6633,0.7233,0.7771,0.8166,0.8466,0.8661,0.8816],
 [0.1762,0.2755,0.3543,0.4204,0.4751,0.5177,0.5569,0.5894,0.622,0.6533,0.7146,0.7697,0.8099,0.8408,0.8608,0.8769],
 [0.1696,0.2663,0.344,0.41,0.4635,0.5062,0.5448,0.578,0.6109,0.644,0.7066,0.7622,0.8031,0.8351,0.8556,0.8722],
 [0.1632,0.2578,0.3341,0.3996,0.4531,0.4956,0.534,0.5671,0.601,0.6345,0.6986,0.7548,0.7963,0.8294,0.8503,0.8675],
 [0.1577,0.2502,0.3257,0.3891,0.4427,0.4851,0.5239,0.5562,0.5911,0.625,0.6907,0.748,0.7895,0.8237,0.8451,0.8628],
 [0.1523,0.2426,0.3172,0.3799,0.4327,0.4752,0.5138,0.5466,0.5814,0.6158,0.6833,0.7412,0.7834,0.8183,0.8399,0.8583],
 [0.1473,0.235,0.309,0.3715,0.4226,0.4655,0.5041,0.537,0.572,0.6072,0.6763,0.7345,0.7773,0.813,0.8348,0.8539],
 [0.143,0.2278,0.301,0.3631,0.4126,0.4561,0.4949,0.5277,0.5626,0.5986,0.6693,0.7278,0.7712,0.8077,0.83,0.8495],
 [0.1388,0.2217,0.2931,0.3547,0.4039,0.4472,0.4856,0.5186,0.5542,0.59,0.6623,0.7211,0.7651,0.8022,0.8253,0.845],
 [0.1348,0.2156,0.2858,0.3464,0.3956,0.4384,0.4763,0.5095,0.5458,0.5813,0.6548,0.7148,0.7593,0.7967,0.8205,0.8405],
 [0.1309,0.2096,0.2785,0.3393,0.388,0.4298,0.4683,0.5014,0.5375,0.5727,0.6473,0.7085,0.7536,0.7914,0.8157,0.8359],
 [0.1274,0.2038,0.2718,0.3324,0.3807,0.4226,0.4605,0.4934,0.5304,0.5645,0.6397,0.7022,0.748,0.7864,0.8106,0.8313],
 [0.1244,0.1981,0.2653,0.3257,0.3736,0.4154,0.4528,0.4855,0.5232,0.5574,0.6323,0.6959,0.7423,0.7815,0.8056,0.8268],
 [0.1214,0.1924,0.259,0.3197,0.3681,0.4095,0.4469,0.4791,0.5166,0.5503,0.6255,0.6896,0.7367,0.7765,0.8005,0.8224],
 [0.1188,0.1877,0.2543,0.3138,0.3625,0.4038,0.4411,0.4727,0.5103,0.5432,0.6187,0.6835,0.731,0.7715,0.7955,0.818],
 [0.1161,0.1832,0.2496,0.3078,0.3569,0.3981,0.4354,0.4663,0.504,0.5363,0.6119,0.6776,0.7255,0.7663,0.7905,0.8135],
 [0.1135,0.1788,0.2447,0.3019,0.3512,0.3923,0.4297,0.4605,0.4978,0.5301,0.6056,0.6717,0.7204,0.7611,0.7857,0.8092],
 [0.1109,0.1743,0.2395,0.2959,0.3455,0.3863,0.4239,0.4547,0.4916,0.5239,0.5993,0.6657,0.7154,0.756,0.781,0.8049],
 [0.1083,0.17,0.2343,0.2902,0.3399,0.3802,0.4182,0.449,0.4847,0.5177,0.5931,0.6599,0.7103,0.7508,0.7762,0.8005],
 [0.1057,0.1674,0.2292,0.2847,0.3344,0.3748,0.4124,0.4433,0.4777,0.5118,0.5868,0.6541,0.7053,0.7457,0.7714,0.7962],
 [0.1031,0.1649,0.2246,0.2792,0.3289,0.3697,0.4069,0.4378,0.4714,0.5061,0.5811,0.6484,0.7003,0.7405,0.7669,0.7918],
 [0.1005,0.1624,0.2202,0.2747,0.3234,0.3647,0.4015,0.4322,0.4662,0.5004,0.5757,0.6426,0.6952,0.7354,0.7628,0.7875],
 [0.0979,0.1599,0.2157,0.2705,0.3187,0.3594,0.396,0.4267,0.461,0.4947,0.5703,0.6369,0.6903,0.7304,0.7587,0.7833],
 [0.0953,0.1568,0.2113,0.2662,0.3144,0.354,0.3905,0.4212,0.4557,0.4891,0.5649,0.6314,0.6856,0.7256,0.7545,0.779],
 [0.0928,0.1538,0.2071,0.2615,0.31,0.3488,0.385,0.4158,0.4503,0.4836,0.5595,0.6261,0.6808,0.7208,0.7504,0.7747],
 [0.0902,0.1507,0.2029,0.2569,0.3055,0.3442,0.3794,0.411,0.445,0.478,0.5541,0.6207,0.6761,0.716,0.7461,0.7705],
 [0.0882,0.1477,0.1993,0.2526,0.3009,0.3395,0.3739,0.4061,0.4399,0.473,0.5487,0.6154,0.6713,0.7114,0.7417,0.7662],
 [0.0866,0.1444,0.1957,0.2488,0.2963,0.3349,0.3684,0.4008,0.4348,0.4682,0.5433,0.6101,0.6666,0.707,0.7373,0.7619],
 [0.0851,0.1411,0.1921,0.2451,0.2919,0.3304,0.3637,0.3955,0.4298,0.4634,0.538,0.6051,0.6619,0.7025,0.7329,0.7576],
 [0.0835,0.1377,0.1887,0.2418,0.2877,0.3259,0.3589,0.3904,0.4249,0.4582,0.5329,0.6,0.6572,0.6981,0.7286,0.7534],
 [0.082,0.1344,0.1855,0.2385,0.2836,0.3215,0.3541,0.3852,0.4199,0.4529,0.5279,0.5949,0.6524,0.6936,0.7245,0.7491],
 [0.0804,0.1313,0.1823,0.2353,0.2794,0.3172,0.3493,0.3801,0.415,0.4476,0.5228,0.5898,0.6481,0.6897,0.7203,0.7448],
 [0.0792,0.1292,0.1799,0.2321,0.2759,0.3129,0.3453,0.3755,0.4101,0.4423,0.5178,0.5852,0.644,0.6857,0.7162,0.7406],
 [0.078,0.127,0.1777,0.2289,0.2724,0.3087,0.3413,0.3714,0.4056,0.438,0.513,0.5809,0.6399,0.6818,0.712,0.7368],
 [0.0768,0.1249,0.1755,0.2257,0.2689,0.3046,0.3372,0.3674,0.4016,0.4336,0.5083,0.5766,0.6358,0.6779,0.7079,0.7329],
 [0.0756,0.1235,0.1733,0.2233,0.2656,0.3007,0.3332,0.3634,0.3975,0.4292,0.5039,0.5723,0.632,0.674,0.704,0.7291],
 [0.0745,0.1224,0.1712,0.221,0.2623,0.2967,0.3291,0.3594,0.3935,0.4249,0.4998,0.5678,0.6285,0.6702,0.7001,0.7254],
 [0.0733,0.1213,0.1696,0.2188,0.2595,0.2928,0.325,0.3555,0.389,0.4208,0.4957,0.5633,0.625,0.6664,0.6962,0.7219],
 [0.0721,0.1203,0.1681,0.2166,0.2568,0.2892,0.3209,0.3516,0.3844,0.4167,0.4916,0.5588,0.6215,0.6626,0.6926,0.7184],
 [0.071,0.1194,0.1666,0.2139,0.2542,0.2857,0.317,0.3476,0.3799,0.4131,0.4875,0.5542,0.6179,0.6589,0.6891,0.7148],
 [0.0698,0.1184,0.165,0.2111,0.2515,0.2822,0.3135,0.3437,0.376,0.4096,0.4834,0.5497,0.6144,0.6552,0.6856,0.7113],
 [0.0686,0.1174,0.1635,0.2082,0.2489,0.2787,0.3099,0.3397,0.3723,0.4062,0.4794,0.5451,0.6109,0.6516,0.6821,0.7078],
]

_P_ARR = np.array(_P_TABLE, dtype=float)   # shape (65, 16)
_P_N_ARR = np.array(_P_N, dtype=float)
_P_Y_ARR = np.array(_P_Y, dtype=float)


# ═══════════════════════════════════════════════════════════════════
# PRIEBE n0 BASIC IMPROVEMENT TABLE  (from V9 spreadsheet "F2 Data")
# ═══════════════════════════════════════════════════════════════════
# x     = log10(Ds/Dc)  where Ds = equiv. unit-cell diameter, Dc = SC diameter
# n     = Ds/Dc = 10^x  →  area replacement ratio ar ≈ 1/n² (circular unit cell)
# x range: 0.30 → 2.00 step 0.02  (n range: 2.0 → 100, ar range: 0.25 → 0.0001)
# Phi columns: 35°, 37.5°, 40°, 42.5°, 45°, 47.5°, 50°, 52.5°, 55°
#
# Use: n0 = n0_priebe_lookup(ar, phi_deg)
#      This gives the theoretical maximum improvement (infinite grid / no stiffness limit).
#      For single-footing treated settlement the composite-modulus factor n governs.

_F2_PHI = [35.0, 37.5, 40.0, 42.5, 45.0, 47.5, 50.0, 52.5, 55.0]
_F2_X   = [round(0.30 + 0.02*i, 4) for i in range(86)]   # 0.30 to 2.00

_F2_TABLE = [  # 86 rows x 9 phi columns, from Priebe V9 spreadsheet
 [3.59109223, 4.09030073, 4.67152297, 5.35211586, 6.15438106, 7.10736808, 8.24948789, 9.63238309, 11.3267971],
 [3.28322331, 3.73788955, 4.26749143, 4.8879059, 5.61952511, 6.48890379, 7.53114741, 8.79344845, 10.34044922],
 [3.01300838, 3.42865219, 3.91300942, 4.48065897, 5.15031844, 5.94635482, 6.90097456, 8.05746686, 9.47512212],
 [2.77416225, 3.15538162, 3.59980593, 4.12086727, 4.73580424, 5.46705159, 6.3442553, 7.40725678, 8.71061858],
 [2.5617226, 2.91238756, 3.32135055, 3.80102387, 4.36733144, 5.04099074, 5.84937212, 6.82925252, 8.03099196],
 [2.37171926, 2.69511733, 3.07241832, 3.51512243, 4.03797831, 4.66016862, 5.40702991, 6.3126003, 7.42348354],
 [2.200938, 2.499885, 2.84877893, 3.25829998, 3.74214073, 4.31810514, 5.00970305, 5.8485126, 6.87776355],
 [2.04674873, 2.3236744, 2.64697069, 3.02657703, 3.47523271, 4.00949753, 4.65123323, 5.42979856, 6.38537917],
 [1.90697853, 2.16399354, 2.46413342, 2.81666559, 3.23346511, 3.72996444, 4.32653225, 5.05051689, 5.93934648],
 [1.77981641, 2.01876544, 2.2978832, 2.62582507, 3.01367962, 3.47585394, 4.03135909, 4.70571557, 5.53384453],
 [1.66374094, 1.88624513, 2.1462171, 2.45175282, 2.81322263, 3.24409771, 3.76215047, 4.39123403, 5.16398273],
 [1.55746456, 1.76495578, 2.00743992, 2.29249995, 2.62984814, 3.03209878, 3.51589057, 4.10355095, 4.82562196],
 [1.45989028, 1.65363913, 1.88010727, 2.14640583, 2.46164237, 2.83764424, 3.29000961, 3.83966589, 4.51523545],
 [1.37007769, 1.55121641, 1.76298072, 2.01204661, 2.30696435, 2.65883674, 3.08230425, 3.5970063, 4.22979942],
 [1.2872159, 1.45675742, 1.65499239, 1.88819442, 2.164399, 2.49404002, 2.89087443, 3.37335379, 3.96670643],
 [1.21060203, 1.3694558, 1.55521647, 1.77378475, 2.03271942, 2.34183546, 2.71407281, 3.16678505, 3.72369598],
 [1.13962374, 1.28860905, 1.46284636, 1.66789008, 1.9108566, 2.20098698, 2.55046404, 2.97562435, 3.49879854],
 [1.07374514, 1.2136023, 1.37717605, 1.56969851, 1.79787474, 2.07041253, 2.39879165, 2.79840483, 3.29029018],
 [1.01249517, 1.14389507, 1.29758488, 1.47849628, 1.69295112, 1.94916075, 2.25795094, 2.63383685, 3.09665531],
 [0.95545809, 1.07901034, 1.22352501, 1.39365329, 1.59535943, 1.83639182, 2.12696673, 2.48078199, 2.91655607],
 [0.90226556, 1.01852546, 1.15451106, 1.31461126, 1.50445606, 1.73136147, 2.00497481, 2.33823143, 2.74880699],
 [0.85259011, 0.96206464, 1.09011139, 1.24087367, 1.41966865, 1.6334078, 1.8912066, 2.20528798, 2.59235382],
 [0.80613956, 0.90929262, 1.02994091, 1.17199751, 1.3404864, 1.54194011, 1.78497618, 2.08115099, 2.44625579],
 [0.76265243, 0.85990933, 0.97365492, 1.10758622, 1.26645207, 1.45642959, 1.68566949, 1.9651037, 2.30967075],
 [0.72189398, 0.81364541, 0.92094398, 1.04728374, 1.19715509, 1.37640137, 1.59273512, 1.85650246, 2.18184247],
 [0.68365288, 0.77025836, 0.8715295, 0.9907695, 1.13222577, 1.30142782, 1.50567646, 1.75476763, 2.06208998],
 [0.64773837, 0.72952928, 0.82515998, 0.93775408, 1.07133028, 1.2311228, 1.4240451, 1.65937581, 1.94979839],
 [0.6139778, 0.69126008, 0.78160781, 0.88797552, 1.01416647, 1.16513673, 1.34743505, 1.56985311, 1.84441102],
 [0.58221453, 0.65527103, 0.7406665, 0.84119615, 0.96046016, 1.10315241, 1.27547785, 1.48576945, 1.74542265],
 [0.55230613, 0.62139872, 0.7021483, 0.79719983, 0.90996198, 1.04488126, 1.20783835, 1.40673362, 1.65237372],
 [0.52412276, 0.58949425, 0.66588209, 0.7557896, 0.86244465, 0.99006026, 1.14421098, 1.3323889, 1.56484525],
 [0.49754589, 0.55942163, 0.63171164, 0.71678556, 0.81770058, 0.93844914, 1.0843166, 1.26240944, 1.48245445],
 [0.47246701, 0.53105643, 0.59949399, 0.68002312, 0.7755398, 0.88982799, 1.02789969, 1.19649689, 1.40485088],
 [0.44878664, 0.50428459, 0.56909809, 0.64535139, 0.73578812, 0.84399514, 0.97472589, 1.13437764, 1.33171312],
 [0.4264134, 0.47900135, 0.54040358, 0.6126318, 0.69828558, 0.80076536, 0.92457991, 1.07580026, 1.26274581],
 [0.40526323, 0.45511035, 0.51329978, 0.58173686, 0.662885, 0.75996818, 0.87726359, 1.02053333, 1.19767709],
 [0.38525861, 0.43252277, 0.48768466, 0.55254912, 0.62945074, 0.72144652, 0.83259427, 0.9683635, 1.13625626],
 [0.36632801, 0.41115667, 0.46346412, 0.5249602, 0.59785765, 0.68505535, 0.79040334, 0.91909376, 1.07825184],
 [0.34840529, 0.39093628, 0.44055114, 0.49886992, 0.56799003, 0.65066064, 0.75053486, 0.87254193, 1.02344972],
 [0.33142919, 0.37179149, 0.41886524, 0.47418558, 0.53974081, 0.6181383, 0.71284449, 0.8285393, 0.97165161],
 [0.31534293, 0.35365729, 0.39833178, 0.45082127, 0.51301078, 0.58737333, 0.67719842, 0.78692942, 0.92267359],
 [0.3000938, 0.33647337, 0.37888155, 0.42869729, 0.48770786, 0.55825899, 0.64347241, 0.74756707, 0.87634487],
 [0.28563277, 0.32018365, 0.36045022, 0.4077396, 0.46374652, 0.53069613, 0.61155103, 0.71031721, 0.83250666],
 [0.27191423, 0.30473599, 0.34297795, 0.38787932, 0.44104721, 0.50459249, 0.58132688, 0.67505421, 0.79101116],
 [0.25889568, 0.2900818, 0.32640904, 0.36905234, 0.41953586, 0.4798622, 0.55269993, 0.64166102, 0.75172061],
 [0.24653745, 0.27617579, 0.31069155, 0.3511989, 0.39914345, 0.45642519, 0.52557693, 0.61002848, 0.71450654],
 [0.23480252, 0.26297565, 0.295777, 0.33426323, 0.37980556, 0.43420676, 0.49987085, 0.5800547, 0.67924898],
 [0.22365627, 0.25044188, 0.28162014, 0.31819326, 0.36146207, 0.41313715, 0.47550039, 0.55164448, 0.64583579],
 [0.21306631, 0.23853753, 0.26817863, 0.30294033, 0.34405676, 0.39315117, 0.45238958, 0.5247088, 0.61416208],
 [0.2030023, 0.22722798, 0.25541285, 0.28845888, 0.32753705, 0.37418781, 0.43046731, 0.49916435, 0.58412968],
 [0.19343579, 0.21648084, 0.24328572, 0.27470628, 0.3118537, 0.35618998, 0.40966701, 0.4749331, 0.55564657],
 [0.18434012, 0.20626569, 0.23176245, 0.26164257, 0.29696059, 0.33910416, 0.38992629, 0.45194192, 0.5286265],
 [0.17569021, 0.196554, 0.22081041, 0.24923027, 0.28281447, 0.32288019, 0.37118667, 0.43012222, 0.50298856],
 [0.16746253, 0.18731899, 0.21039898, 0.23743421, 0.26937475, 0.307471, 0.35339325, 0.40940962, 0.47865675],
 [0.15963494, 0.17853545, 0.20049938, 0.22622136, 0.25660333, 0.2928324, 0.3364945, 0.38974366, 0.45555969],
 [0.1521866, 0.17017971, 0.19108454, 0.21556066, 0.2444644, 0.27892287, 0.320442, 0.37106754, 0.43363031],
 [0.14509789, 0.16222945, 0.18212902, 0.20542292, 0.23292429, 0.26570337, 0.30519023, 0.35332784, 0.4128055],
 [0.13835032, 0.15466368, 0.17360885, 0.19578066, 0.22195132, 0.2531372, 0.29069639, 0.33647432, 0.39302589],
 [0.13192644, 0.14746261, 0.16550146, 0.18660801, 0.2115157, 0.2411898, 0.27692017, 0.3204597, 0.37423558],
 [0.12580982, 0.14060757, 0.15778556, 0.17788059, 0.20158933, 0.22982863, 0.26382365, 0.30523944, 0.35638195],
 [0.11998493, 0.13408095, 0.1504411, 0.16957542, 0.19214575, 0.21902305, 0.2513711, 0.29077159, 0.33941537],
 [0.1144371, 0.12786612, 0.14344915, 0.16167083, 0.18316003, 0.20874417, 0.23952883, 0.27701664, 0.32328911],
 [0.10915247, 0.12194739, 0.13679182, 0.15414637, 0.17460861, 0.19896473, 0.22826508, 0.26393729, 0.30795906],
 [0.10411795, 0.11630992, 0.13045224, 0.14698273, 0.16646931, 0.18965903, 0.21754992, 0.25149839, 0.29338363],
 [0.09932113, 0.11093968, 0.12441446, 0.14016167, 0.15872113, 0.1808028, 0.20735506, 0.23966676, 0.27952356],
 [0.09475028, 0.1058234, 0.11866338, 0.13366597, 0.15134429, 0.17237314, 0.19765381, 0.22841109, 0.26634181],
 [0.09039432, 0.10094853, 0.11318476, 0.12747932, 0.14432004, 0.16434839, 0.18842099, 0.21770179, 0.25380338],
 [0.08624271, 0.09630318, 0.10796509, 0.12158631, 0.13763071, 0.15670811, 0.17963276, 0.20751094, 0.2418752],
 [0.08228551, 0.0918761, 0.1029916, 0.11597237, 0.13125956, 0.14943296, 0.17126663, 0.19781212, 0.23052604],
 [0.07851326, 0.08765663, 0.09825218, 0.1106237, 0.12519074, 0.14250464, 0.16330132, 0.18858039, 0.21972639],
 [0.07491701, 0.08363466, 0.09373538, 0.10552723, 0.11940928, 0.13590585, 0.15571669, 0.17979214, 0.20944832],
 [0.07148828, 0.07980061, 0.08943035, 0.10067058, 0.11390097, 0.12962021, 0.14849372, 0.17142506, 0.19966542],
 [0.068219, 0.07614541, 0.08532677, 0.09604204, 0.10865239, 0.12363222, 0.14161438, 0.16345802, 0.19035274],
 [0.06510153, 0.07266042, 0.08141491, 0.09163047, 0.1036508, 0.1179272, 0.1350616, 0.15587105, 0.18148662],
 [0.06212861, 0.06933747, 0.07768548, 0.08742535, 0.09888414, 0.11249123, 0.12881923, 0.14864521, 0.17304471],
 [0.05929336, 0.0661688, 0.07412972, 0.08341668, 0.09434095, 0.10731114, 0.12287198, 0.14176259, 0.16500582],
 [0.05658921, 0.06314704, 0.07073928, 0.07959497, 0.09001041, 0.10237443, 0.11720533, 0.13520622, 0.1573499],
 [0.05400997, 0.06026518, 0.06750626, 0.07595124, 0.08588221, 0.09766924, 0.11180555, 0.12896002, 0.15005796],
 [0.05154971, 0.05751659, 0.06442312, 0.07247693, 0.08194659, 0.09318436, 0.1066596, 0.12300874, 0.14311199],
 [0.04920281, 0.05489494, 0.06148274, 0.06916395, 0.07819429, 0.08890911, 0.10175513, 0.11733794, 0.13649494],
 [0.04696394, 0.05239423, 0.05867833, 0.06600459, 0.07461651, 0.08483338, 0.09708041, 0.11193393, 0.13019065],
 [0.04482802, 0.05000874, 0.05600344, 0.06299153, 0.07120491, 0.08094758, 0.09262434, 0.1067837, 0.12418378],
 [0.04279022, 0.04773307, 0.05345197, 0.06011783, 0.06795154, 0.07724259, 0.08837635, 0.10187494, 0.11845981],
 [0.04084594, 0.04556203, 0.05101807, 0.05737688, 0.06484887, 0.07370974, 0.08432643, 0.09719596, 0.11300494],
 [0.03899081, 0.04349073, 0.04869621, 0.05476241, 0.06188975, 0.07034084, 0.08046508, 0.09273566, 0.1078061],
 [0.03722067, 0.04151449, 0.04648113, 0.05226844, 0.05906737, 0.06712805, 0.07678325, 0.0884835, 0.10285089],
]

_F2_ARR  = np.array(_F2_TABLE, dtype=float)
_F2_X_ARR = np.array(_F2_X, dtype=float)
_F2_P_ARR = np.array(_F2_PHI, dtype=float)


def n0_priebe_lookup(ar: float, phi_deg: float) -> float:
    """Basic Priebe improvement factor n0 for infinite grid.
    ar       : area replacement ratio (0 < ar ≤ 1)
    phi_deg  : SC friction angle in degrees (35–55)
    Returns n0 (unconstrained by column stiffness).
    """
    if ar <= 0 or ar > 1:
        return 1.0
    n = 1.0 / math.sqrt(ar)            # Ds/Dc
    x = math.log10(max(n, 10**_F2_X_ARR[0]))   # clamp to table min
    x = min(x, _F2_X_ARR[-1])

    phi_deg = float(np.clip(phi_deg, _F2_P_ARR[0], _F2_P_ARR[-1]))

    ix = int(np.searchsorted(_F2_X_ARR, x, side='right') - 1)
    ix = int(np.clip(ix, 0, len(_F2_X_ARR) - 2))
    fx = (x - _F2_X_ARR[ix]) / (_F2_X_ARR[ix + 1] - _F2_X_ARR[ix])

    ip = int(np.searchsorted(_F2_P_ARR, phi_deg, side='right') - 1)
    ip = int(np.clip(ip, 0, len(_F2_P_ARR) - 2))
    fp = (phi_deg - _F2_P_ARR[ip]) / (_F2_P_ARR[ip + 1] - _F2_P_ARR[ip])

    v00 = _F2_ARR[ix,     ip]
    v10 = _F2_ARR[ix + 1, ip]
    v01 = _F2_ARR[ix,     ip + 1]
    v11 = _F2_ARR[ix + 1, ip + 1]
    return float((1-fx)*(1-fp)*v00 + fx*(1-fp)*v10 +
                 (1-fx)*fp*v01 + fx*fp*v11)


def _priebe_lookup(row_val: float, col_n: float) -> float:
    """Bilinear interpolation of Priebe s/s∞ table.
    row_val = ar * z_into_SC  (0..32)
    col_n   = improvement factor n  (1..40)
    Returns s/s∞ ∈ (0, 1].
    """
    # Clamp
    row_val = max(0.0, min(row_val, _P_Y_ARR[-1]))
    col_n   = max(_P_N_ARR[0], min(col_n, _P_N_ARR[-1]))

    # Row interpolation
    iy = np.searchsorted(_P_Y_ARR, row_val, side='right') - 1
    iy = int(np.clip(iy, 0, len(_P_Y_ARR) - 2))
    fy = (row_val - _P_Y_ARR[iy]) / (_P_Y_ARR[iy + 1] - _P_Y_ARR[iy])

    # Col interpolation — note: _P_N is NOT uniformly spaced (jumps at 10→15, etc.)
    ix = np.searchsorted(_P_N_ARR, col_n, side='right') - 1
    ix = int(np.clip(ix, 0, len(_P_N_ARR) - 2))
    fx = (col_n - _P_N_ARR[ix]) / (_P_N_ARR[ix + 1] - _P_N_ARR[ix])

    # Bilinear
    v00 = _P_ARR[iy,     ix]
    v10 = _P_ARR[iy + 1, ix]
    v01 = _P_ARR[iy,     ix + 1]
    v11 = _P_ARR[iy + 1, ix + 1]
    return float((1-fy)*(1-fx)*v00 + fy*(1-fx)*v10 +
                 (1-fy)*fx*v01 + fy*fx*v11)


# ═══════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SoilLayer:
    name: str = "Layer 1"
    top_elev: float = 100.0       # ft
    unit_weight: float = 110.0    # pcf (total)
    constrained_modulus: float = 500_000.0  # psf
    poisson_ratio: float = 0.33
    num_sublayers: int = 10


@dataclass
class SoilProfile:
    surface_elev: float = 100.0
    gwt_elev: float = 95.0
    firm_elev: float = 80.0
    layers: List[SoilLayer] = field(default_factory=lambda: [
        SoilLayer("Layer 1", 100.0, 105.0, 350_000, 0.33, 10),
        SoilLayer("Layer 2",  90.0, 115.0, 850_000, 0.33, 10),
    ])


@dataclass
class Foundation:
    name: str = "F1"
    footing_type: str = "Square/Rect"   # Square/Rect | Strip | Circular
    width: float = 19.0                 # ft  (B)
    length: float = 19.0               # ft  (L, unused for Strip/Circular)
    base_elev: float = 95.0            # ft  (elevation of bottom of footing)
    bearing_pressure: float = 7_500.0  # psf (net applied)
    tol_treated: float = 2.5           # in
    tol_untreated: float = 4.0         # in


@dataclass
class StoneColumn:
    diameter: float = 3.0             # ft
    num_sc: int = 14                   # per footing
    length: float = 15.0              # ft
    top_elev: float = 95.0            # ft (= base of footing typically)
    em_sc: float = 3_000_000.0        # psf  constrained modulus of SC material
    friction_angle: float = 48.0      # deg
    unit_weight: float = 95.0         # pcf
    stress_change_ratio: float = 2.0/3.0  # fraction of SC length at which stress method switches


@dataclass
class SubResult:
    num: int
    layer_name: str
    top: float
    bot: float
    mid: float
    h: float
    Em: float
    sigma_v: float
    u: float
    sigma_eff: float
    delta_sigma: float           # untreated stress increase
    delta_sigma_tr: float        # treated stress increase (may differ if 4:1→2:1)
    in_sc: bool
    K: float
    n2: float
    s_s_inf: float               # Priebe s/s∞ depth factor (1.0 outside SC zone)
    delta_untr_ft: float
    delta_untr_in: float
    delta_tr_ft: float
    delta_tr_in: float
    cum_untr: float = 0.0
    cum_tr: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# CALCULATION ENGINE
# ═══════════════════════════════════════════════════════════════════

GAMMA_W = 62.4  # pcf


class Calculator:

    # ── Stress Distributions ─────────────────────────────────────────

    @staticmethod
    def _boussinesq_corner_I(m: float, n: float) -> float:
        """Boussinesq influence factor under corner of m×n loaded area (m=B/z, n=L/z)."""
        M = m * m + n * n
        MN2 = m * m * n * n
        sqM1 = math.sqrt(M + 1.0)
        t1 = 2.0 * m * n * sqM1 * (M + 2.0) / ((M + 1.0 + MN2) * (M + 1.0))
        denom2 = M + 1.0 - MN2
        arg = 2.0 * m * n * sqM1
        if abs(denom2) < 1e-14:
            t2 = math.pi / 2.0
        elif denom2 > 0:
            t2 = math.atan(arg / denom2)
        else:
            t2 = math.pi + math.atan(arg / denom2)
        return (t1 + t2) / (4.0 * math.pi)

    @classmethod
    def stress_boussinesq(cls, B: float, L: float, q: float, z: float,
                          ftype: str) -> float:
        if z < 0.001:
            return q
        if ftype == "Strip":
            alpha = math.atan(B / (2.0 * z))
            return q * (2.0 / math.pi) * (alpha + math.sin(alpha) * math.cos(alpha))
        elif ftype == "Circular":
            r = B / 2.0
            return q * (1.0 - 1.0 / (1.0 + (r / z) ** 2) ** 1.5)
        else:
            m = (B / 2.0) / z
            n = (L / 2.0) / z
            return q * 4.0 * cls._boussinesq_corner_I(m, n)

    @staticmethod
    def stress_2to1(B: float, L: float, q: float, z: float, ftype: str) -> float:
        if z <= 0:
            return q
        if ftype == "Strip":
            return q * B / (B + z)
        elif ftype == "Circular":
            D = B
            return q * (D / (D + z)) ** 2
        return q * B * L / ((B + z) * (L + z))

    @staticmethod
    def stress_4to1(B: float, L: float, q: float, z: float, ftype: str) -> float:
        """4V:1H spread — 0.25 horizontal per 1 vertical on each side."""
        if z <= 0:
            return q
        sp = z / 4.0
        if ftype == "Strip":
            return q * B / (B + 2.0 * sp)
        elif ftype == "Circular":
            D = B
            return q * (D / (D + 2.0 * sp)) ** 2
        return q * B * L / ((B + 2.0 * sp) * (L + 2.0 * sp))

    @staticmethod
    def stress_westergaard(B: float, L: float, q: float, z: float,
                            mu: float, ftype: str) -> float:
        """Westergaard (1938) vertical stress — accounts for horizontal reinforcing layers."""
        if z < 0.001:
            return q
        eta = math.sqrt((1.0 - 2.0 * mu) / (2.0 * (1.0 - mu)))
        if ftype == "Strip":
            alpha = math.atan(B / (2.0 * z))
            return q * (2.0 / math.pi) * (alpha + math.sin(alpha) * math.cos(alpha))
        elif ftype == "Circular":
            r = B / 2.0
            Iw = 1.0 / math.sqrt(1.0 + 2.0 * (r / (z * eta)) ** 2 * (math.pi / 2.0))
            return q * (1.0 - Iw)
        else:
            m = (B / 2.0) / z
            n = (L / 2.0) / z
            d2 = m * m + n * n + eta * eta * m * m * n * n
            if d2 < 1e-14:
                return q
            I_corner = (1.0 / (2.0 * math.pi)) * math.atan(m * n / (eta * math.sqrt(d2)))
            return q * 4.0 * I_corner

    @classmethod
    def stress_4to1_2to1(cls, B: float, L: float, q: float, z: float,
                          ftype: str, z_change: float) -> float:
        """Treated stress: 4V:1H from BOF, then 2V:1H below z_change.
        z_change is typically 2/3 × SC length (depth from BOF).
        """
        if z <= z_change:
            return cls.stress_4to1(B, L, q, z, ftype)
        # Effective dimensions at the transition depth using 4V:1H
        sp = z_change / 4.0
        dz = z - z_change           # depth below transition point
        if ftype == "Strip":
            B_eff = B + 2.0 * sp
            q_eff = q * B / B_eff
            return cls.stress_2to1(B_eff, B_eff, q_eff, dz, "Strip")
        elif ftype == "Circular":
            D_eff = B + 2.0 * sp
            q_eff = q * (B / D_eff) ** 2
            return cls.stress_2to1(D_eff, D_eff, q_eff, dz, "Circular")
        else:
            B_eff = B + 2.0 * sp
            L_eff = L + 2.0 * sp
            q_eff = q * B * L / (B_eff * L_eff)
            return cls.stress_2to1(B_eff, L_eff, q_eff, dz, ftype)

    @classmethod
    def stress_at(cls, method: str, B: float, L: float, q: float, z: float,
                  ftype: str, mu: float = 0.33, z_change: float = 0.0) -> float:
        if method == "Boussinesq":
            return cls.stress_boussinesq(B, L, q, z, ftype)
        elif method == "2:1":
            return cls.stress_2to1(B, L, q, z, ftype)
        elif method == "4:1":
            return cls.stress_4to1(B, L, q, z, ftype)
        elif method == "4:1→2:1":
            return cls.stress_4to1_2to1(B, L, q, z, ftype, z_change)
        elif method == "Westergaard":
            return cls.stress_westergaard(B, L, q, z, mu, ftype)
        return cls.stress_boussinesq(B, L, q, z, ftype)

    # ── In-Situ Stress ────────────────────────────────────────────────

    @staticmethod
    def insitu_stress(elev_mid: float, layers: List[SoilLayer],
                      surface_elev: float, gwt_elev: float,
                      firm_elev: float):
        """Total vertical stress, pore pressure, effective stress at elevation."""
        layers_desc = sorted(layers, key=lambda l: l.top_elev, reverse=True)
        sigma_v = 0.0
        for i, layer in enumerate(layers_desc):
            top = min(surface_elev, layer.top_elev)
            bot = layers_desc[i + 1].top_elev if i + 1 < len(layers_desc) else firm_elev
            calc_top = top
            calc_bot = max(bot, elev_mid)
            if calc_top > calc_bot:
                sigma_v += layer.unit_weight * (calc_top - calc_bot)
            if bot <= elev_mid:
                break
        u = max(0.0, GAMMA_W * (gwt_elev - elev_mid))
        return sigma_v, u, max(0.0, sigma_v - u)

    # ── Main Calculation ──────────────────────────────────────────────

    @classmethod
    def run(cls, profile: SoilProfile, fnd: Foundation, sc: StoneColumn,
            untreated_method: str, treated_method: str = "4:1→2:1") -> dict:
        B, L = fnd.width, fnd.length
        q = fnd.bearing_pressure
        BOF = fnd.base_elev
        ftype = fnd.footing_type

        if ftype == "Strip":
            A_found = B
        elif ftype == "Circular":
            A_found = math.pi * (B / 2.0) ** 2
        else:
            A_found = B * L

        A_sc_each = math.pi * sc.diameter ** 2 / 4.0
        A_sc_total = sc.num_sc * A_sc_each
        ar = A_sc_total / A_found if A_found > 0 else 0.0

        SC_top = sc.top_elev
        SC_bot = SC_top - sc.length
        firm = profile.firm_elev

        # Build sublayer sequence using each layer's FULL thickness for subdivision
        layers_desc = sorted(profile.layers, key=lambda l: l.top_elev, reverse=True)
        raw_sublayers = []

        for i, layer in enumerate(layers_desc):
            lay_top = min(profile.surface_elev, layer.top_elev)
            if i + 1 < len(layers_desc):
                lay_bot = layers_desc[i + 1].top_elev
            else:
                lay_bot = firm
            lay_bot = max(lay_bot, firm)
            thickness = lay_top - lay_bot
            if thickness <= 0:
                continue
            h_sub = thickness / layer.num_sublayers
            for j in range(layer.num_sublayers):
                sub_top = lay_top - j * h_sub
                sub_bot = sub_top - h_sub
                if sub_bot < firm - 1e-6:
                    sub_bot = firm
                if sub_top <= firm + 1e-6:
                    break
                raw_sublayers.append({
                    "top": sub_top, "bot": sub_bot,
                    "Em": layer.constrained_modulus,
                    "uw": layer.unit_weight,
                    "mu": layer.poisson_ratio,
                    "name": layer.name,
                })

        raw_sublayers.sort(key=lambda s: -s["top"])

        results: List[SubResult] = []
        cum_untr = 0.0
        cum_tr = 0.0

        for idx, sub in enumerate(raw_sublayers):
            mid = (sub["top"] + sub["bot"]) / 2.0
            h = sub["top"] - sub["bot"]
            z = BOF - mid
            Em_s = sub["Em"]
            mu = sub["mu"]

            sigma_v, u, sigma_eff = cls.insitu_stress(
                mid, profile.layers, profile.surface_elev,
                profile.gwt_elev, firm
            )

            # Stress change depth for treated (4:1→2:1): 2/3 × SC length from BOF
            z_change = sc.stress_change_ratio * sc.length

            # ── Untreated stress ──────────────────────────────────────
            if z <= 0.001:
                delta_sigma = 0.0
            else:
                delta_sigma = cls.stress_at(untreated_method, B, L, q, z, ftype, mu)

            # ── Treated stress (may differ from untreated) ────────────
            if z <= 0.001:
                delta_sigma_tr = 0.0
            else:
                delta_sigma_tr = cls.stress_at(treated_method, B, L, q, z,
                                               ftype, mu, z_change)

            # Untreated settlement
            delta_untr_ft = delta_sigma / Em_s * h if (Em_s > 0 and z > 0) else 0.0
            delta_untr_in = delta_untr_ft * 12.0

            # Is sublayer within stone column zone?
            in_sc = (sub["top"] <= SC_top + 1e-4) and (sub["bot"] >= SC_bot - 1e-4)

            if in_sc and z > 0.001 and Em_s > 0:
                K = sc.em_sc / Em_s
                # Composite modulus improvement factor: n2 = 1 + ar*(K-1)
                n2 = 1.0 + ar * (K - 1.0)
                # Priebe s/s∞ depth correction
                z_into_sc_bot = SC_top - sub["bot"]
                row = ar * z_into_sc_bot
                s_s_inf = _priebe_lookup(row, n2)
                # Treated settlement uses treated stress + Priebe improvement
                delta_tr_ft = (delta_sigma_tr / Em_s) * h * s_s_inf / n2
            else:
                K = 1.0
                n2 = 1.0
                s_s_inf = 1.0
                delta_tr_ft = delta_untr_ft

            delta_tr_in = delta_tr_ft * 12.0
            cum_untr += delta_untr_in
            cum_tr += delta_tr_in

            results.append(SubResult(
                num=idx + 1,
                layer_name=sub["name"],
                top=sub["top"],
                bot=sub["bot"],
                mid=mid,
                h=h,
                Em=Em_s,
                sigma_v=sigma_v,
                u=u,
                sigma_eff=sigma_eff,
                delta_sigma=delta_sigma,
                delta_sigma_tr=delta_sigma_tr,
                in_sc=in_sc,
                K=round(sc.em_sc / Em_s, 4) if Em_s > 0 else 1.0,
                n2=n2,
                s_s_inf=s_s_inf,
                delta_untr_ft=delta_untr_ft,
                delta_untr_in=delta_untr_in,
                delta_tr_ft=delta_tr_ft,
                delta_tr_in=delta_tr_in,
                cum_untr=cum_untr,
                cum_tr=cum_tr,
            ))

        treated_total = sum(r.delta_tr_in for r in results)
        untreated_total = sum(r.delta_untr_in for r in results)

        n0_basic = n0_priebe_lookup(ar, sc.friction_angle) if ar > 0 else 1.0

        return {
            "sublayers": results,
            "treated_total_in": treated_total,
            "untreated_total_in": untreated_total,
            "ar": ar,
            "A_found": A_found,
            "A_sc_total": A_sc_total,
            "n0_basic": n0_basic,          # theoretical Priebe n0 (infinite grid)
            "z_change": sc.stress_change_ratio * sc.length,
        }


# ═══════════════════════════════════════════════════════════════════
# STYLE
# ═══════════════════════════════════════════════════════════════════

APP_STYLE = """
QWidget          { font-size: 12px; color: #1a202c; }
QMainWindow      { background: #f0f2f5; }
QLabel           { color: #1a202c; background: transparent; }

QGroupBox {
    font-weight: bold;
    border: 1px solid #c9d3e0;
    border-radius: 5px;
    margin-top: 10px;
    padding: 6px 8px;
    background: white;
    color: #1a202c;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #2c5282;
}

QTabWidget::pane { border: 1px solid #c9d3e0; background: white; }
QTabBar::tab {
    padding: 5px 14px; background: #e2e8f0; color: #1a202c;
    border: 1px solid #c9d3e0; border-bottom: none;
    border-radius: 4px 4px 0 0;
}
QTabBar::tab:selected { background: white; font-weight: bold; color: #2c5282; }

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    border: 1px solid #cbd5e0; border-radius: 3px;
    padding: 3px 6px;
    background: white; color: #1a202c;
    min-height: 22px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #4299e1;
}
QLineEdit[readOnly="true"] { background: #f7fafc; color: #4a5568; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button,       QSpinBox::down-button {
    background: #e2e8f0; border: none; width: 16px;
}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover,
QSpinBox::up-button:hover,       QSpinBox::down-button:hover {
    background: #cbd5e0;
}
QComboBox QAbstractItemView {
    background: white; color: #1a202c;
    selection-background-color: #bee3f8;
    selection-color: #1a202c;
}

QPushButton {
    background: #2b6cb0; color: white; border: none;
    padding: 6px 18px; border-radius: 4px; font-weight: bold;
    min-height: 28px;
}
QPushButton:hover { background: #2c7be5; }
QPushButton:pressed { background: #1e4e8c; }
QPushButton#secondary {
    background: #718096; padding: 4px 12px; font-weight: normal;
    min-height: 24px;
}
QPushButton#secondary:hover { background: #4a5568; }
QPushButton#danger {
    background: #c53030; padding: 4px 12px; font-weight: normal;
    min-height: 24px;
}

QTableWidget {
    gridline-color: #e2e8f0;
    alternate-background-color: #f7fafc;
    background: white;
    selection-background-color: #bee3f8;
    selection-color: #1a202c;
}
QHeaderView::section {
    background: #2b6cb0; color: white; padding: 4px 6px;
    font-weight: bold; border: none;
    border-right: 1px solid #2c7be5;
}
QStatusBar { background: #edf2f7; color: #4a5568; }
"""


# ═══════════════════════════════════════════════════════════════════
# HELPER WIDGETS
# ═══════════════════════════════════════════════════════════════════

def _dspin(val, lo, hi, dec=2, step=1.0, suffix="") -> QDoubleSpinBox:
    sp = QDoubleSpinBox()
    sp.setRange(lo, hi)
    sp.setDecimals(dec)
    sp.setSingleStep(step)
    sp.setValue(val)
    if suffix:
        sp.setSuffix("  " + suffix)
    sp.setMinimumWidth(110)
    return sp


def _ispin(val, lo=1, hi=10000) -> QSpinBox:
    sp = QSpinBox()
    sp.setRange(lo, hi)
    sp.setValue(val)
    sp.setMinimumWidth(80)
    return sp


def _sep():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #e2e8f0;")
    return line


# ═══════════════════════════════════════════════════════════════════
# SOIL PROFILE WIDGET  — with multi-profile save/load manager
# ═══════════════════════════════════════════════════════════════════

class SoilProfileWidget(QWidget):
    """Soil profile editor with named profile save/load and JSON file I/O."""

    # Default profile loaded on startup
    _DEFAULT_PROFILE = {
        "surface_elev": 100.0, "gwt_elev": 95.0, "firm_elev": 80.0,
        "layers": [
            {"name": "Layer 1", "top_elev": 100.0, "unit_weight": 105.0,
             "constrained_modulus": 350_000, "poisson_ratio": 0.33, "num_sublayers": 10},
            {"name": "Layer 2", "top_elev":  90.0, "unit_weight": 115.0,
             "constrained_modulus": 850_000, "poisson_ratio": 0.33, "num_sublayers": 10},
        ]
    }

    def __init__(self):
        super().__init__()
        self._profiles: dict = {}       # name → profile dict
        self._current_name: str = ""
        self._build()
        # Seed with one default profile
        self._profiles["Soil 1"] = self._DEFAULT_PROFILE.copy()
        self._profiles["Soil 1"]["layers"] = [d.copy() for d in self._DEFAULT_PROFILE["layers"]]
        self._load_into_form("Soil 1")
        self._refresh_selector()

    # ── Build UI ─────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        # ── Profile manager bar ──────────────────────────────────────
        mgr_group = QGroupBox("Soil Profile Library")
        mg = QVBoxLayout(mgr_group)
        mg.setSpacing(4)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Active profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.setToolTip("Select a saved profile to load it")
        row1.addWidget(self.profile_combo, 1)
        mg.addLayout(row1)

        row2 = QHBoxLayout()
        self.profile_name_edit = QLineEdit("Soil 1")
        self.profile_name_edit.setPlaceholderText("Profile name …")
        self.profile_name_edit.setMinimumWidth(120)
        row2.addWidget(self.profile_name_edit, 1)

        self.save_btn   = QPushButton("Save")
        self.save_btn.setObjectName("secondary")
        self.save_btn.setToolTip("Save current inputs under this name")
        self.new_btn    = QPushButton("New")
        self.new_btn.setObjectName("secondary")
        self.new_btn.setToolTip("Clear form for a new profile")
        self.del_btn_p  = QPushButton("Delete")
        self.del_btn_p.setObjectName("danger")
        self.del_btn_p.setToolTip("Remove this profile from the library")
        for b in (self.save_btn, self.new_btn, self.del_btn_p):
            b.setMinimumWidth(54)
        row2.addWidget(self.save_btn)
        row2.addWidget(self.new_btn)
        row2.addWidget(self.del_btn_p)
        mg.addLayout(row2)

        row3 = QHBoxLayout()
        self.export_btn = QPushButton("Export JSON …")
        self.export_btn.setObjectName("secondary")
        self.import_btn = QPushButton("Import JSON …")
        self.import_btn.setObjectName("secondary")
        row3.addWidget(self.import_btn)
        row3.addWidget(self.export_btn)
        row3.addStretch()
        mg.addLayout(row3)

        layout.addWidget(mgr_group)

        # ── Site elevations ──────────────────────────────────────────
        elev_group = QGroupBox("Site Elevations")
        eg = QGridLayout(elev_group)
        eg.setSpacing(6)
        eg.setContentsMargins(8, 10, 8, 8)
        eg.setColumnMinimumWidth(0, 150)   # label column never collapses
        eg.setColumnStretch(1, 1)          # spin column takes remaining space

        self.surface_elev = _dspin(100.0, -999, 9999, 2, 1.0, "ft")
        self.gwt_elev     = _dspin(95.0,  -999, 9999, 2, 1.0, "ft")
        self.firm_elev    = _dspin(80.0,  -999, 9999, 2, 1.0, "ft")

        for row_i, (lbl_text, widget) in enumerate([
            ("Surface Elevation:",    self.surface_elev),
            ("Groundwater Table:",    self.gwt_elev),
            ("Firm Layer Elevation:", self.firm_elev),
        ]):
            lbl = QLabel(lbl_text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            eg.addWidget(lbl, row_i, 0)
            eg.addWidget(widget, row_i, 1)

        layout.addWidget(elev_group)

        # ── Layers table ─────────────────────────────────────────────
        layers_group = QGroupBox("Soil Layers  (top → bottom)")
        ll = QVBoxLayout(layers_group)

        lbtn = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Layer")
        self.add_btn.setObjectName("secondary")
        self.del_btn = QPushButton("Remove Selected")
        self.del_btn.setObjectName("danger")
        lbtn.addWidget(self.add_btn)
        lbtn.addWidget(self.del_btn)
        lbtn.addStretch()
        ll.addLayout(lbtn)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Layer Name", "Top Elev (ft)", "Unit Wt (pcf)",
             "E_m (psf)", "Poisson's ν", "Sublayers"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(170)
        ll.addWidget(self.table)
        layout.addWidget(layers_group)

        # Connections
        self.add_btn.clicked.connect(self._add_layer)
        self.del_btn.clicked.connect(self._del_layer)
        self.save_btn.clicked.connect(self._save_profile)
        self.new_btn.clicked.connect(self._new_profile)
        self.del_btn_p.clicked.connect(self._delete_profile)
        self.export_btn.clicked.connect(self._export_json)
        self.import_btn.clicked.connect(self._import_json)
        self.profile_combo.currentTextChanged.connect(self._on_combo_select)

    # ── Profile manager logic ─────────────────────────────────────────

    def _refresh_selector(self):
        """Rebuild combo box from current _profiles keys."""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for name in sorted(self._profiles.keys()):
            self.profile_combo.addItem(name)
        # Select current
        idx = self.profile_combo.findText(self._current_name)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    def _on_combo_select(self, name: str):
        if name and name in self._profiles:
            self._load_into_form(name)

    def _save_profile(self):
        name = self.profile_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Save Profile", "Enter a profile name first.")
            return
        self._profiles[name] = self._snapshot()
        self._current_name = name
        self._refresh_selector()

    def _new_profile(self):
        # Suggest a name
        existing = set(self._profiles.keys())
        i = 1
        while f"Soil {i}" in existing:
            i += 1
        new_name = f"Soil {i}"
        self.profile_name_edit.setText(new_name)
        self._current_name = new_name
        # Clear form to defaults
        self.surface_elev.setValue(100.0)
        self.gwt_elev.setValue(95.0)
        self.firm_elev.setValue(80.0)
        self.table.setRowCount(0)
        self._insert_row(SoilLayer("Layer 1", 100.0, 110.0, 500_000, 0.33, 10))

    def _delete_profile(self):
        name = self._current_name
        if not name or name not in self._profiles:
            return
        reply = QMessageBox.question(
            self, "Delete Profile",
            f'Delete profile "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self._profiles[name]
        if self._profiles:
            first = sorted(self._profiles.keys())[0]
            self._load_into_form(first)
        else:
            self._new_profile()
        self._refresh_selector()

    def _snapshot(self) -> dict:
        """Capture current form state as a dict."""
        layers = []
        for row in range(self.table.rowCount()):
            try:
                sp = self.table.cellWidget(row, 5)
                layers.append({
                    "name": (self.table.item(row, 0).text()
                             if self.table.item(row, 0) else f"Layer {row+1}"),
                    "top_elev":            float(self.table.item(row, 1).text()),
                    "unit_weight":         float(self.table.item(row, 2).text()),
                    "constrained_modulus": float(self.table.item(row, 3).text()),
                    "poisson_ratio":       float(self.table.item(row, 4).text()),
                    "num_sublayers":       sp.value() if sp else 10,
                })
            except (ValueError, AttributeError):
                continue
        return {
            "surface_elev": self.surface_elev.value(),
            "gwt_elev":     self.gwt_elev.value(),
            "firm_elev":    self.firm_elev.value(),
            "layers":       layers,
        }

    def _load_into_form(self, name: str):
        """Populate form fields from a saved profile dict."""
        data = self._profiles.get(name)
        if not data:
            return
        self._current_name = name
        self.profile_name_edit.setText(name)
        self.surface_elev.setValue(data.get("surface_elev", 100.0))
        self.gwt_elev.setValue(data.get("gwt_elev", 95.0))
        self.firm_elev.setValue(data.get("firm_elev", 80.0))
        self.table.setRowCount(0)
        for ld in data.get("layers", []):
            self._insert_row(SoilLayer(
                name=ld.get("name", "Layer"),
                top_elev=ld.get("top_elev", 100.0),
                unit_weight=ld.get("unit_weight", 110.0),
                constrained_modulus=ld.get("constrained_modulus", 500_000),
                poisson_ratio=ld.get("poisson_ratio", 0.33),
                num_sublayers=ld.get("num_sublayers", 10),
            ))

    # ── JSON I/O ─────────────────────────────────────────────────────

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Soil Profiles", "soil_profiles.json",
            "JSON files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._profiles, f, indent=2)
            QMessageBox.information(
                self, "Export",
                f"Saved {len(self._profiles)} profile(s) to:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Soil Profiles", "",
            "JSON files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object with profile names as keys.")
            # Merge (overwrite on name collision)
            added = 0
            for name, pdata in data.items():
                if isinstance(pdata, dict) and "layers" in pdata:
                    self._profiles[name] = pdata
                    added += 1
            self._refresh_selector()
            QMessageBox.information(
                self, "Import", f"Imported {added} profile(s) from:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    # ── Layer table helpers ───────────────────────────────────────────

    def _insert_row(self, layer: SoilLayer = None):
        if layer is None:
            n = self.table.rowCount()
            prev_top = 90.0
            if n > 0:
                try:
                    prev_top = float(self.table.item(n - 1, 1).text()) - 5.0
                except Exception:
                    pass
            layer = SoilLayer(f"Layer {n + 1}", prev_top, 110.0, 500_000, 0.33, 10)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(layer.name))
        for col, val in enumerate(
            [layer.top_elev, layer.unit_weight,
             layer.constrained_modulus, layer.poisson_ratio], start=1
        ):
            itm = QTableWidgetItem(f"{val:.6g}")
            itm.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, itm)
        sp = QSpinBox()
        sp.setRange(1, 200)
        sp.setValue(layer.num_sublayers)
        self.table.setCellWidget(row, 5, sp)

    def _add_layer(self):
        self._insert_row()

    def _del_layer(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    # ── Public API (unchanged for Calculator) ─────────────────────────

    def get_profile(self) -> SoilProfile:
        profile = SoilProfile(
            surface_elev=self.surface_elev.value(),
            gwt_elev=self.gwt_elev.value(),
            firm_elev=self.firm_elev.value(),
            layers=[],
        )
        for row in range(self.table.rowCount()):
            try:
                name = (self.table.item(row, 0).text()
                        if self.table.item(row, 0) else f"Layer {row + 1}")
                top  = float(self.table.item(row, 1).text())
                uw   = float(self.table.item(row, 2).text())
                em   = float(self.table.item(row, 3).text())
                mu   = float(self.table.item(row, 4).text())
                sp   = self.table.cellWidget(row, 5)
                nsub = sp.value() if sp else 10
                profile.layers.append(SoilLayer(name, top, uw, em, mu, nsub))
            except (ValueError, AttributeError):
                continue
        return profile


# ═══════════════════════════════════════════════════════════════════
# FOUNDATION WIDGET
# ═══════════════════════════════════════════════════════════════════

class FoundationWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        g = QGroupBox("Foundation Details")
        f = QFormLayout(g)
        f.setSpacing(7)

        self.name     = QLineEdit("F1")
        self.ftype    = QComboBox()
        self.ftype.addItems(["Square/Rect", "Strip", "Circular"])
        self.width    = _dspin(19.0,  0.5, 5000.0, 2, 0.5,  "ft  (B)")
        self.length   = _dspin(19.0,  0.5, 5000.0, 2, 0.5,  "ft  (L)")
        self.base_elev = _dspin(95.0, -999, 9999,  2, 1.0,  "ft")
        self.load_kips = _dspin(2707.5, 0, 1e9,  1, 10.0,  "kips")
        self.bearing   = _dspin(7500.0, 0, 1e7,  0, 100.0, "psf")
        self.tol_tr    = _dspin(2.5,    0,  24.0, 2, 0.25,  "in")
        self.tol_untr  = _dspin(4.0,    0,  24.0, 2, 0.25,  "in")

        self.len_row_label = QLabel("Length (L):")
        f.addRow("Footing Name:",  self.name)
        f.addRow("Footing Type:",  self.ftype)
        f.addRow("Width (B):",     self.width)
        f.addRow(self.len_row_label, self.length)
        f.addRow("Base Elevation:", self.base_elev)
        f.addRow("Applied Load:",   self.load_kips)
        f.addRow("Bearing Pressure:", self.bearing)
        f.addRow(_sep(), QWidget())
        f.addRow("Tol. Treated Sett.:",   self.tol_tr)
        f.addRow("Tol. Untreated Sett.:", self.tol_untr)

        layout.addWidget(g)

        # Auto-calc bearing pressure from load / area
        for w in (self.load_kips, self.width, self.length):
            w.valueChanged.connect(self._auto_bearing)
        self.ftype.currentTextChanged.connect(self._auto_bearing)
        self.ftype.currentTextChanged.connect(self._toggle_length)

        layout.addStretch()

    def _toggle_length(self, ftype: str):
        show = (ftype == "Square/Rect")
        self.len_row_label.setVisible(show)
        self.length.setVisible(show)

    def _auto_bearing(self):
        try:
            ftype = self.ftype.currentText()
            B = self.width.value()
            L = self.length.value()
            P = self.load_kips.value() * 1000.0
            if ftype == "Strip":
                area = B
            elif ftype == "Circular":
                area = math.pi * (B / 2.0) ** 2
            else:
                area = B * L
            if area > 0:
                self.bearing.blockSignals(True)
                self.bearing.setValue(P / area)
                self.bearing.blockSignals(False)
        except Exception:
            pass

    def get_foundation(self) -> Foundation:
        return Foundation(
            name=self.name.text(),
            footing_type=self.ftype.currentText(),
            width=self.width.value(),
            length=self.length.value(),
            base_elev=self.base_elev.value(),
            bearing_pressure=self.bearing.value(),
            tol_treated=self.tol_tr.value(),
            tol_untreated=self.tol_untr.value(),
        )


# ═══════════════════════════════════════════════════════════════════
# STONE COLUMN WIDGET
# ═══════════════════════════════════════════════════════════════════

class StoneColumnWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        g = QGroupBox("Stone Column Details")
        f = QFormLayout(g)
        f.setSpacing(7)

        self.diam      = _dspin(3.0,   0.1, 50.0,  2, 0.5,  "ft")
        self.num_sc    = _ispin(14, 1, 100_000)
        self.length    = _dspin(15.0,  1.0, 500.0, 1, 1.0,  "ft")
        self.top_elev  = _dspin(95.0, -999, 9999,  2, 1.0,  "ft")
        self.em_sc     = _dspin(3_000_000.0, 1_000, 1e9, 0, 50_000.0, "psf")
        self.phi       = _dspin(48.0, 20.0, 75.0,  1, 1.0,  "deg")
        self.uw_sc     = _dspin(95.0, 50.0, 200.0, 1, 1.0,  "pcf")
        self.sc_ratio  = _dspin(2.0/3.0, 0.0, 1.0, 4, 0.05)

        # Read-only display fields
        self.area_each = QLineEdit()
        self.area_each.setReadOnly(True)
        self.area_total = QLineEdit()
        self.area_total.setReadOnly(True)
        self.ar_display = QLineEdit()
        self.ar_display.setReadOnly(True)

        f.addRow("Diameter:",                  self.diam)
        f.addRow("No. of SC per Footing:",     self.num_sc)
        f.addRow("SC Length:",                 self.length)
        f.addRow("Top Elevation of SC:",       self.top_elev)
        f.addRow("SC Constrained Modulus:",    self.em_sc)
        f.addRow("SC Friction Angle:",         self.phi)
        f.addRow("SC Unit Weight:",            self.uw_sc)
        f.addRow("Stress Change Ratio (2/3):", self.sc_ratio)
        f.addRow(_sep(), QWidget())
        f.addRow("Area per SC (ft²):",         self.area_each)
        f.addRow("Total SC Area (ft²):",       self.area_total)
        f.addRow("Area Replacement Ratio:",    self.ar_display)

        layout.addWidget(g)
        layout.addStretch()

        self.diam.valueChanged.connect(self._update_display)
        self.num_sc.valueChanged.connect(self._update_display)
        self._update_display()

    def _update_display(self):
        d = self.diam.value()
        n = self.num_sc.value()
        a_each = math.pi * d ** 2 / 4.0
        a_total = n * a_each
        self.area_each.setText(f"{a_each:.4f}")
        self.area_total.setText(f"{a_total:.4f}")
        self.ar_display.setText("(set by foundation area)")

    def update_ar(self, A_found: float):
        try:
            d = self.diam.value()
            n = self.num_sc.value()
            a_total = n * math.pi * d ** 2 / 4.0
            ar = a_total / A_found if A_found > 0 else 0.0
            self.ar_display.setText(f"{ar:.4f}  ({ar * 100:.1f}%)")
        except Exception:
            pass

    def get_sc(self) -> StoneColumn:
        return StoneColumn(
            diameter=self.diam.value(),
            num_sc=self.num_sc.value(),
            length=self.length.value(),
            top_elev=self.top_elev.value(),
            em_sc=self.em_sc.value(),
            friction_angle=self.phi.value(),
            unit_weight=self.uw_sc.value(),
            stress_change_ratio=self.sc_ratio.value(),
        )


# ═══════════════════════════════════════════════════════════════════
# SETTLEMENT PROFILE CHART
# ═══════════════════════════════════════════════════════════════════

class SettlementChart(FigureCanvasQTAgg):
    def __init__(self):
        self._fig = Figure(figsize=(5, 5), dpi=96, tight_layout=True)
        super().__init__(self._fig)
        self._ax = self._fig.add_subplot(111)
        self.setMinimumHeight(260)
        self._draw_empty()

    def _draw_empty(self):
        self._ax.set_xlabel("Cumulative Settlement (in)", fontsize=9)
        self._ax.set_ylabel("Elevation (ft)", fontsize=9)
        self._ax.set_title("Settlement Profile", fontsize=10)
        self._ax.grid(True, alpha=0.3)
        self._ax.tick_params(labelsize=8)
        self.draw()

    def update_plot(self, res: dict, fnd: Foundation, sc: StoneColumn,
                    profile: SoilProfile):
        ax = self._ax
        ax.clear()

        sublayers: List[SubResult] = res["sublayers"]
        if not sublayers:
            self._draw_empty()
            return

        # Only plot sublayers with z > 0 (below footing)
        active = [r for r in sublayers if r.delta_sigma > 0 or r.in_sc]
        if not active:
            active = [r for r in sublayers if r.cum_tr > 0 or r.cum_untr > 0]
        if not active:
            active = sublayers

        elevs   = [r.mid for r in active]
        cum_tr  = [r.cum_tr for r in active]
        cum_untr = [r.cum_untr for r in active]

        ax.plot(cum_untr, elevs, "b-o", markersize=3,
                linewidth=1.5, label="Untreated")
        ax.plot(cum_tr, elevs,   "r-s", markersize=3,
                linewidth=1.5, label="Treated (Priebe)")

        # SC zone shading
        sc_bot = sc.top_elev - sc.length
        ax.axhspan(sc_bot, sc.top_elev, alpha=0.08, color="green")
        ax.axhline(sc.top_elev, color="green", linestyle="--",
                   linewidth=0.8, label="SC Zone", alpha=0.7)
        ax.axhline(sc_bot, color="green", linestyle="--",
                   linewidth=0.8, alpha=0.7)

        # Stress change depth marker (4:1→2:1 transition)
        z_ch = sc.stress_change_ratio * sc.length
        elev_change = sc.top_elev - z_ch
        if sc_bot < elev_change < sc.top_elev:
            ax.axhline(elev_change, color="orange", linestyle="-.",
                       linewidth=1.0, alpha=0.8,
                       label=f"4:1→2:1 ({elev_change:.1f} ft)")

        # Firm layer
        ax.axhline(profile.firm_elev, color="sienna", linewidth=1.2,
                   linestyle=":", label="Firm Layer")

        # Tolerance lines
        if fnd.tol_treated > 0:
            ax.axvline(fnd.tol_treated, color="red", linestyle="--",
                       linewidth=0.8, alpha=0.6,
                       label=f"Tol. Tr. ({fnd.tol_treated:.1f}\")")
        if fnd.tol_untreated > 0:
            ax.axvline(fnd.tol_untreated, color="blue", linestyle="--",
                       linewidth=0.8, alpha=0.6,
                       label=f"Tol. Untr. ({fnd.tol_untreated:.1f}\")")

        ax.set_xlabel("Cumulative Settlement (in)", fontsize=9)
        ax.set_ylabel("Elevation (ft)", fontsize=9)
        ax.set_title(f"Settlement Profile — {fnd.name}", fontsize=10)
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=8)

        y_min = profile.firm_elev - 1.0
        y_max = fnd.base_elev + 3.0
        ax.set_ylim(y_min, y_max)

        self.draw()


# ═══════════════════════════════════════════════════════════════════
# RESULTS WIDGET
# ═══════════════════════════════════════════════════════════════════

_GREEN_OK  = "#276749"
_RED_FAIL  = "#c53030"
_BLUE_INFO = "#2b6cb0"


class ResultsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Summary panel ────────────────────────────────────────────
        sum_group = QGroupBox("Settlement Summary")
        sg = QGridLayout(sum_group)
        sg.setSpacing(8)

        def _make_result_label():
            lbl = QLabel("—")
            font = lbl.font()
            font.setPointSize(13)
            font.setBold(True)
            lbl.setFont(font)
            return lbl

        self.lbl_treated   = _make_result_label()
        self.lbl_untreated = _make_result_label()
        self.lbl_ar        = QLabel("—")
        self.lbl_n_avg     = QLabel("—")
        self.lbl_n0_basic  = QLabel("—")
        self.lbl_A_found   = QLabel("—")
        self.lbl_A_sc      = QLabel("—")
        self.lbl_z_change  = QLabel("—")
        self.status_tr     = QLabel("")
        self.status_untr   = QLabel("")

        sg.addWidget(QLabel("Treated Settlement:"),    0, 0)
        sg.addWidget(self.lbl_treated,                 0, 1)
        sg.addWidget(self.status_tr,                   0, 2)
        sg.addWidget(QLabel("Untreated Settlement:"),  1, 0)
        sg.addWidget(self.lbl_untreated,               1, 1)
        sg.addWidget(self.status_untr,                 1, 2)
        sg.addWidget(QLabel("Area Replacement Ratio:"),2, 0)
        sg.addWidget(self.lbl_ar,                      2, 1)
        sg.addWidget(QLabel("Avg. n (composite):"),    2, 2)
        sg.addWidget(self.lbl_n_avg,                   2, 3)
        sg.addWidget(QLabel("n₀ Basic (inf. grid):"),  3, 0)
        sg.addWidget(self.lbl_n0_basic,                3, 1)
        sg.addWidget(QLabel("Stress Change Depth:"),   3, 2)
        sg.addWidget(self.lbl_z_change,                3, 3)
        sg.addWidget(QLabel("Foundation Area (ft²):"), 4, 0)
        sg.addWidget(self.lbl_A_found,                 4, 1)
        sg.addWidget(QLabel("Total SC Area (ft²):"),   4, 2)
        sg.addWidget(self.lbl_A_sc,                    4, 3)

        layout.addWidget(sum_group)

        # ── Tabs: table and chart ────────────────────────────────────
        tabs = QTabWidget()

        # Sublayer table
        COL_HEADERS = [
            "#", "Layer", "Top\n(ft)", "Bot\n(ft)", "h\n(ft)",
            "Eₘ\n(psf)", "σᵥ\n(psf)", "u\n(psf)", "σ'\n(psf)",
            "Δσ Untr.\n(psf)", "Δσ Tr.\n(psf)", "SC?", "K", "n₂", "s/s∞",
            "Untr. Δ\n(in)", "Tr. Δ\n(in)", "Cum. Tr.\n(in)"
        ]
        self.table = QTableWidget(0, len(COL_HEADERS))
        self.table.setHorizontalHeaderLabels(COL_HEADERS)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setStretchLastSection(False)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(260)
        tabs.addTab(self.table, "Sublayer Details")

        # Chart
        self.chart = SettlementChart()
        tabs.addTab(self.chart, "Settlement Profile")

        layout.addWidget(tabs, 1)

    def _color_status(self, val: float, limit: float) -> str:
        return _GREEN_OK if val <= limit else _RED_FAIL

    def show_results(self, res: dict, fnd: Foundation,
                     sc: StoneColumn, profile: SoilProfile):
        sublayers: List[SubResult] = res["sublayers"]
        s_tr  = res["treated_total_in"]
        s_untr = res["untreated_total_in"]
        ar    = res["ar"]

        # Summary
        c_tr   = self._color_status(s_tr,   fnd.tol_treated)
        c_untr = self._color_status(s_untr, fnd.tol_untreated)

        self.lbl_treated.setText(f"{s_tr:.3f} in")
        self.lbl_treated.setStyleSheet(f"color: {c_tr}; font-weight: bold;")
        ok_tr = "✓ OK" if s_tr <= fnd.tol_treated else f"✗ > {fnd.tol_treated:.2f} in"
        self.status_tr.setText(ok_tr)
        self.status_tr.setStyleSheet(f"color: {c_tr}; font-weight: bold;")

        self.lbl_untreated.setText(f"{s_untr:.3f} in")
        self.lbl_untreated.setStyleSheet(f"color: {c_untr}; font-weight: bold;")
        ok_untr = "✓ OK" if s_untr <= fnd.tol_untreated else f"✗ > {fnd.tol_untreated:.2f} in"
        self.status_untr.setText(ok_untr)
        self.status_untr.setStyleSheet(f"color: {c_untr}; font-weight: bold;")

        self.lbl_ar.setText(f"{ar:.4f}  ({ar * 100:.1f}%)")
        self.lbl_A_found.setText(f"{res['A_found']:.2f}")
        self.lbl_A_sc.setText(f"{res['A_sc_total']:.2f}")

        n0 = res.get("n0_basic", 0.0)
        self.lbl_n0_basic.setText(
            f"{n0:.3f}  (φ={sc.friction_angle:.1f}°, ar={ar:.3f})")

        z_ch = sc.stress_change_ratio * sc.length
        elev_ch = sc.top_elev - z_ch
        self.lbl_z_change.setText(
            f"{z_ch:.2f} ft  ({sc.stress_change_ratio:.3f}×L, elev {elev_ch:.1f} ft)"
        )

        sc_subs = [r for r in sublayers if r.in_sc]
        if sc_subs:
            avg_n = sum(r.n2 for r in sc_subs) / len(sc_subs)
            self.lbl_n_avg.setText(f"{avg_n:.3f}")
        else:
            self.lbl_n_avg.setText("—")

        # Sublayer table
        SC_COLOR = QColor("#d1fae5")   # light green for SC zone rows
        ABOVE_COLOR = QColor("#f7fafc")

        self.table.setRowCount(0)
        for r in sublayers:
            row = self.table.rowCount()
            self.table.insertRow(row)

            vals = [
                str(r.num),
                r.layer_name,
                f"{r.top:.2f}",
                f"{r.bot:.2f}",
                f"{r.h:.3f}",
                f"{r.Em:,.0f}",
                f"{r.sigma_v:.1f}",
                f"{r.u:.1f}",
                f"{r.sigma_eff:.1f}",
                f"{r.delta_sigma:.1f}",
                f"{r.delta_sigma_tr:.1f}",
                "●" if r.in_sc else "",
                f"{r.K:.2f}" if r.in_sc else "—",
                f"{r.n2:.3f}" if r.in_sc else "—",
                f"{r.s_s_inf:.4f}" if r.in_sc else "—",
                f"{r.delta_untr_in:.4f}",
                f"{r.delta_tr_in:.4f}",
                f"{r.cum_tr:.4f}",
            ]

            bg = SC_COLOR if r.in_sc else (
                ABOVE_COLOR if row % 2 == 0 else QColor("white")
            )
            for col, val in enumerate(vals):
                itm = QTableWidgetItem(val)
                itm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                itm.setBackground(bg)
                self.table.setItem(row, col, itm)

        # Chart
        self.chart.update_plot(res, fnd, sc, profile)


# ═══════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Priebe Stone Column Settlement Calculator")
        self.resize(1450, 870)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(APP_STYLE)
        self._build()

    def _build(self):
        # ── Toolbar ──────────────────────────────────────────────────
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))

        tb.addWidget(QLabel("  Untreated: "))
        self.untr_combo = QComboBox()
        self.untr_combo.addItems(["Boussinesq", "2:1 (2V:1H)", "Westergaard"])
        self.untr_combo.setMinimumWidth(148)
        tb.addWidget(self.untr_combo)
        tb.addSeparator()

        tb.addWidget(QLabel("  Treated: "))
        self.tr_combo = QComboBox()
        self.tr_combo.addItems(["4:1→2:1 (Priebe)", "Boussinesq", "Westergaard"])
        self.tr_combo.setMinimumWidth(148)
        tb.addWidget(self.tr_combo)
        tb.addSeparator()

        self.calc_btn = QPushButton("  Calculate  ")
        self.calc_btn.setStyleSheet("font-size: 13px; font-weight: bold; "
                                    "padding: 4px 20px; background: #276749;")
        self.calc_btn.clicked.connect(self._calculate)
        tb.addWidget(self.calc_btn)
        tb.addSeparator()

        proj_lbl = QLabel("  Project: ")
        tb.addWidget(proj_lbl)
        self.proj_name = QLineEdit("Untitled")
        self.proj_name.setMinimumWidth(160)
        self.proj_name.setMaximumWidth(260)
        tb.addWidget(self.proj_name)
        tb.addWidget(QLabel("  No.: "))
        self.proj_num = QLineEdit("ET-000")
        self.proj_num.setMaximumWidth(100)
        tb.addWidget(self.proj_num)

        # ── Central layout ────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left: input tabs  (no max-width — splitter handle lets user resize freely)
        input_w = QWidget()
        input_w.setMinimumWidth(320)
        iv = QVBoxLayout(input_w)
        iv.setContentsMargins(4, 4, 4, 0)

        self.input_tabs = QTabWidget()
        self.soil_w = SoilProfileWidget()
        self.fnd_w  = FoundationWidget()
        self.sc_w   = StoneColumnWidget()
        self.input_tabs.addTab(self.soil_w, "Soil Profile")
        self.input_tabs.addTab(self.fnd_w,  "Foundation")
        self.input_tabs.addTab(self.sc_w,   "Stone Columns")
        iv.addWidget(self.input_tabs)

        help_lbl = QLabel(
            "Tip: Fill Soil Profile → Foundation → Stone Columns, then click Calculate."
        )
        help_lbl.setStyleSheet("color: #718096; font-size: 11px; padding: 4px;")
        help_lbl.setWordWrap(True)
        iv.addWidget(help_lbl)

        splitter.addWidget(input_w)

        # Right: results
        self.results_w = ResultsWidget()
        splitter.addWidget(self.results_w)
        splitter.setSizes([450, 1000])
        splitter.setHandleWidth(6)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #cbd5e0; border-radius: 3px; }"
            "QSplitter::handle:hover { background: #4299e1; }"
        )

        # Status bar
        self.statusBar().showMessage("Ready — Enter inputs and click Calculate.")

    def _calculate(self):
        try:
            profile = self.soil_w.get_profile()
            fnd     = self.fnd_w.get_foundation()
            sc      = self.sc_w.get_sc()

            # Parse method strings (first token before any space)
            untr_text = self.untr_combo.currentText()
            tr_text   = self.tr_combo.currentText()
            untr_method = untr_text.split(" ")[0]           # "Boussinesq", "2:1", "Westergaard"
            tr_method   = tr_text.split(" ")[0]             # "4:1→2:1", "Boussinesq", "Westergaard"

            # Basic validation
            if not profile.layers:
                QMessageBox.warning(self, "Input Error",
                                    "No soil layers defined in the Soil Profile tab.")
                return
            if profile.firm_elev >= fnd.base_elev:
                QMessageBox.warning(self, "Input Error",
                                    "Firm layer elevation must be BELOW the base of footing.")
                return
            if sc.top_elev > fnd.base_elev + 0.01:
                QMessageBox.warning(self, "Input Error",
                                    "Stone column top elevation cannot be above base of footing.")
                return
            if sc.top_elev - sc.length < profile.firm_elev - 0.01:
                reply = QMessageBox.question(
                    self, "Check SC Length",
                    f"SC tip elevation ({sc.top_elev - sc.length:.1f} ft) is below "
                    f"firm layer ({profile.firm_elev:.1f} ft).\n"
                    "Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return

            res = Calculator.run(profile, fnd, sc, untr_method, tr_method)

            if not res["sublayers"]:
                QMessageBox.warning(self, "No Results",
                                    "No sublayers were computed. Check soil profile elevations.")
                return

            self.results_w.show_results(res, fnd, sc, profile)
            self.sc_w.update_ar(res["A_found"])

            tr    = res["treated_total_in"]
            untr  = res["untreated_total_in"]
            n_sub = len(res["sublayers"])
            ar    = res["ar"]
            n0    = res.get("n0_basic", 0.0)
            self.statusBar().showMessage(
                f"{n_sub} sublayers  |  "
                f"Treated: {tr:.3f} in  |  Untreated: {untr:.3f} in  |  "
                f"ar = {ar:.3f}  |  n₀ (inf. grid) = {n0:.2f}  |  "
                f"Untr: {untr_text}  Tr: {tr_text}"
            )

        except Exception as exc:
            QMessageBox.critical(self, "Calculation Error",
                                 f"An error occurred:\n\n{exc}")
            import traceback
            traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Priebe Settlement Calculator")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
