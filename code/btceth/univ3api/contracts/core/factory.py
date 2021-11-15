import math
import os
import json
from typing import Optional
from datetime import datetime
from eth_typing.encoding import HexStr
from hexbytes.main import HexBytes
from univ3api.contracts.base import BaseLocalContractAPI
from web3 import Web3
import web3
from univ3api.contracts.enums import PoolFee


ABI_FILE = "UniswapV3Factory.json"
CONTRACT_ADDRESS = "0x1F98431c8aD98523631AE4a59f267346ea31F984"


def get_abi():
    pwd, _ = os.path.split(__file__)
    with open(os.path.join(pwd, ABI_FILE), "r") as f:
        return json.load(f)["abi"]


class UniswapV3Factory(BaseLocalContractAPI):

    def __init__(self, api: Web3, account: web3.Account):
        contract = api.eth.contract(CONTRACT_ADDRESS, abi=get_abi())
        super().__init__(api, contract, account)

    def get_pool(self, token0: str, token1: str, fee: PoolFee) -> HexStr:
        return self.contract.functions.getPool(token0, token1, fee.value).call()