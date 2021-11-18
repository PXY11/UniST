# -*- coding: utf-8 -*-
"""
Created on Mon Nov 15 09:45:33 2021

@author: YS
"""
import pandas as pd
import datetime
import pickle
##这些信号数据都是在VecTool backtest中使用过的

def load_obj(name):
    with open(name + '.pkl', 'rb') as f:
        return pickle.load(f)
symbolSigDataAvgUDP = load_obj('../../data/btceth/symbolsSigAvg_2018050220211110_1440min_v15_udp')['1440min']
UDP60 = symbolSigDataAvgUDP.iloc[:,4].copy(deep=True)

#UDP60.to_csv('../data/symbolsSig/UDP60.csv')
df_ma = pd.read_csv('../../data/btceth/MA.csv',index_col=0)
df_ma.dropna(axis=0,inplace=True)
