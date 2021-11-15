import math
import os
import json
from typing import Optional
from datetime import datetime
from hexbytes.main import HexBytes
from univ3api.contracts.base import BaseLocalContractAPI
from web3 import Web3
import web3
from univ3api.contracts.enums import PoolFee


ABI_FILE = "UniswapV3Pool.json"


def get_abi():
    pwd, _ = os.path.split(__file__)
    with open(os.path.join(pwd, ABI_FILE), "r") as f:
        return json.load(f)["abi"]


class UniswapV3Pool(BaseLocalContractAPI):

    def __init__(self, contract_address: str, api: Web3, account: web3.Account):
        contract = api.eth.contract(contract_address, abi=get_abi())
        super().__init__(api, contract, account)

    def slot0(self):
        return self.contract.functions.slot0().call()