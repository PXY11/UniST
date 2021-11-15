from web3 import Web3
import web3
from web3.contract import Contract, ContractFunction
from typing import Optional, Union
import logging


class BaseLocalContractAPI(object):

    def __init__(self, api: Web3, contract: Contract, account: web3.Account):
        self.api = api
        self.contract = contract
        self.account = account
        self.api.eth.default_account = account.address
    
    def send_transaction(self, function: ContractFunction, trx_params: Optional[dict]=None):
        if "nonce" not in trx_params:
            count = self.api.eth.get_transaction_count(self.account.address)
            trx_params["nonce"] = count
        trx = function.buildTransaction(trx_params)
        signed_tx = self.account.sign_transaction(trx)
        tx_hash = self.api.eth.send_raw_transaction(signed_tx.rawTransaction)
        logging.info(f"transaction hash: {tx_hash}")
        self.api.eth.wait_for_transaction_receipt(tx_hash)
        trx = self.api.eth.get_transaction(tx_hash)
        receipt = self.api.eth.get_transaction_receipt(tx_hash)
        return trx, receipt
    
    def transact_with_return(
        self, function: ContractFunction, 
        trx_params: Optional[dict]=None, 
        events: Optional[list]=None,
        call_before_transaction=True,
        ):
        if call_before_transaction:
            call_result = function.call(trx_params)
        else:
            call_result = None

        t, r = self.send_transaction(function, trx_params)
        logs = []
        if events:
            for event in events:
                logs.extend(event.processReceipt(r))
        return {
            "trx_send": True,
            "transaction": t,
            "receipt": r,
            "events": logs,
            "call_result": call_result
        }
    


        
        
    