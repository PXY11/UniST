import os
import json
from typing import Optional
from datetime import datetime
from hexbytes.main import HexBytes
from univ3api.contracts.base import BaseLocalContractAPI
from web3 import Web3
import web3
from univ3api.contracts.enums import PoolFee


ABI_FILE = "ERC20.json"


def get_abi():
    pwd, _ = os.path.split(__file__)
    with open(os.path.join(pwd, ABI_FILE), "r") as f:
        return json.load(f)["abi"]


class ERC20Token(BaseLocalContractAPI):

    def __init__(self, token_address: str, api: Web3, account: web3.Account):
        contract = api.eth.contract(token_address, abi=get_abi())
        super().__init__(api, contract, account)
        self._decimals = 0
        self._decimals_called = False

    def call(self, func_name: str, *args, **trx_params):
        return self.contract.get_function_by_name(func_name)(*args).call(trx_params)
    
    def decimals(self):
        if self._decimals_called:
            return self._decimals
        else:
            self._decimals = self.call("decimals")
            self._decimals_called = True
            return self._decimals
    