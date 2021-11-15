
from enum import Enum
import math
import os
import json
import posixpath
from typing import Optional, Tuple, Union
from datetime import datetime
from univ3api.contracts.erc20 import ERC20Token
from hexbytes.main import HexBytes
from univ3api.contracts.base import BaseLocalContractAPI
from web3 import Web3, contract
import web3
from univ3api.contracts.enums import PoolFee
from univ3api.contracts.core.factory import UniswapV3Factory
from univ3api.contracts.core.pool import UniswapV3Pool


ABI_FILE = "NonfungiblePositionManager.json"
CONTRACT_ADDRESS = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"

MAX_ERC20_AMOUNT = 0xffffffffffffffffffffffffffffffff
EMPTY_ADDRESS = "0x0000000000000000000000000000000000000000"


def get_abi():
    pwd, _ = os.path.split(__file__)
    with open(os.path.join(pwd, ABI_FILE), "r") as f:
        return json.load(f)["abi"]


class NonfungiblePositionManager(BaseLocalContractAPI): 
    
    def __init__(self, api: Web3, account: web3.Account):
        """API for Liquidity Pool operation.

        Solidity documentation: https://docs.uniswap.org/protocol/reference/periphery/NonfungiblePositionManager

        :param api: Web3 object
        :type api: Web3
        :param account: web3.Account object
        :type account: web3.Account
        """
        contract = api.eth.contract(CONTRACT_ADDRESS, abi=get_abi())
        super().__init__(api, contract, account)
        self._weth9: str = ""
        self.default_deadline=60
        self.call_only = False
        self.pool_contracts = {}
        self.erc20_token_contracts = {}
        self.factory_contract = UniswapV3Factory(self.api, self.account)
    
    def get_pool(self, token0: str, token1: str, fee: PoolFee) -> UniswapV3Pool:
        key = (token0, token1, fee)
        if (token0, token1, fee) in self.pool_contracts:
            pool = self.pool_contracts[key]
        else:
            pool_addr = self.factory_contract.get_pool(token0, token1, fee)
            pool = UniswapV3Pool(pool_addr,self.api, self.account)
            self.pool_contracts[key] = pool
        return pool
    
    def get_erc20_token(self, address: str):
        if address in self.erc20_token_contracts:
            return self.erc20_token_contracts[address]
        else:
            self.erc20_token_contracts[address] = ERC20Token(address, self.api, self.account)
            return self.erc20_token_contracts[address]
    
    def weth9(self):
        if not self._weth9:
            self._weth9 = self.contract.functions.WETH9().call()
        return self._weth9
            
    POSITION_KEYS = (
        "nonce",
        "operator",
        "token0",
        "token1",
        "fee",
        "tickLower",
        "tickUpper",
        "liquidity",
        "feeGrowthInside0LastX128",
        "feeGrowthInside1LastX128",
        "tokensOwed0",
        "tokensOwed1"
    )

    def eth_owed_in_position(self, token_id: Optional[int]=None, position: Optional[dict]=None):
        assert token_id or position, "At least one param should be parsed: token_id or position."
        if not position:
            position = self.positions(token_id)
        
        weth9 = self.weth9()
        for n in (0, 1):
            if position[f"token{n}"] == weth9:
                return True, n

        return False, -1

    def positions(self, token_id: int) -> dict:
        """Get position infomation by position token id

        Solidity documentation: 
            https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#positions

        :param token_id: The ID of the token that represents the position
        :type token_id: int
        :return: position infomation
        :rtype: dict

        """
        r = self.contract.get_function_by_name("positions")(token_id).call()
        return dict(zip(self.POSITION_KEYS, r))

    def collect(self, token_id: int, amount0Max: int=MAX_ERC20_AMOUNT, amount1Max: int=MAX_ERC20_AMOUNT, **trx_params) -> dict:
        """Collect fees from position

        Solidity documentation: 
            https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#collect
            https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#collectparams

        :param token_id: The ID of the token that represents the position
        :type token_id: int
        :param amount0Max: max amount of token0 to collect, defaults to MAX_ERC20_AMOUNT
        :type amount0Max: int, optional
        :param amount1Max: max amount of token1 to collect, defaults to MAX_ERC20_AMOUNT
        :type amount1Max: int, optional
        :return: transation data
        :rtype: dict

        >>> transaction data: 
            {
                "trx_sent": True, // The transaction will never be sent if there is no fee to collect.
                "events": [CollectEventDict]
            }
        
        CollectEventDict, see: https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#collect-1
            
        """
        collect_params = dict(
            tokenId=token_id,
            recipient=self.account.address,
            amount0Max=int(amount0Max),
            amount1Max=int(amount1Max)
        )

        collect = self.contract.functions.collect(collect_params)
        amounts = collect.call(trx_params)
        if (not amounts[0]) and (not amounts[1]):
            return {
                "trx_sent": False,
                "reason": "No collectable fee available.",
                "call_result": amounts 
            }

        position = self.positions(token_id)
        is_eth, pos = self.eth_owed_in_position(position=position)
        if is_eth:
            erc20_pos = int(pos==0)
            collect_params["recipient"] = EMPTY_ADDRESS
            function = self.multicall(
                self.contract.encodeABI("collect", args=[collect_params]),
                self.contract.encodeABI("unwrapWETH9", args=[0, self.account.address]),
                self.contract.encodeABI("sweepToken", args=[position[f"token{erc20_pos}"], amounts[erc20_pos], self.account.address])
            )
            call_before_transation = True
        else:
            function = collect
            call_before_transation = False
        
        if self.call_only:
            call_result = function.call(trx_params)
            return {
                "trx_sent": False,
                "reason": "call only",
                "call_result": call_result
            }
        result = self.transact_with_return(function, trx_params, [self.contract.events.Collect()], call_before_transation)
        if not call_before_transation:
            result["call_result"] = amounts
        return result
    
    def position_balance(self, token_id: int):
        position = self.positions(token_id)
        params = dict(
            tokenId=token_id,
            liquidity=position["liquidity"],
            amount0Min=0,
            amount1Min=0,
            deadline=int(datetime.now().timestamp()+self.default_deadline)
        )
        balance = self.contract.get_function_by_name("decreaseLiquidity")(params).call()
        position["balance"] = balance
        return position

    def decreaseLiquidity(self, token_id: int, liquidity: Optional[int]=None, percentage: Optional[float]=1, **trx_params) -> dict:
        """DecreaseLiquidity from a position to self.account


        :param token_id: The ID of the token that represents the position
        :type token_id: int
        :param liquidity: The amount of liquidity intend to decrease, defaults to None
        :type liquidity: Optional[int], optional
        :param percentage: liquidity to decrease = position.liquidity * percentage, defaults to 1
        :type percentage: Optional[float], optional
        :return: transaction data
        :rtype: dict

        >>> transaction data
            {
                events: [DecreaseLiquidityDict]
            }

        DecreaseLiquidityDict see: https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#decreaseliquidity
        """

        position = self.positions(token_id)
        if not liquidity:
            liquidity = int(position["liquidity"] * percentage)
        else:
            liquidity = min(liquidity, position["liquidity"])
        params = dict(
            tokenId=token_id,
            liquidity=liquidity,
            amount0Min=0,
            amount1Min=0,
            deadline=int(datetime.now().timestamp()+self.default_deadline)
        )
        if self.call_only:
            return self.contract.get_function_by_name("decreaseLiquidity")(params).call()
        collect_params = dict(
            tokenId=token_id,
            recipient=self.account.address,
            amount0Max=MAX_ERC20_AMOUNT,
            amount1Max=MAX_ERC20_AMOUNT
        )

        collect = self.contract.functions.collect(collect_params)
        amounts = collect.call(trx_params)
        
        position = self.positions(token_id)
        is_eth, pos = self.eth_owed_in_position(position=position)
        if is_eth:
            erc20_pos = int(pos==0)
            collect_params["recipient"] = EMPTY_ADDRESS
            function = self.multicall(
                self.contract.encodeABI("decreaseLiquidity", args=[params]),
                self.contract.encodeABI("collect", args=[collect_params]),
                self.contract.encodeABI("unwrapWETH9", args=[0, self.account.address]),
                self.contract.encodeABI("sweepToken", args=[position[f"token{erc20_pos}"], amounts[erc20_pos], self.account.address])
            )
        else:
            function = self.multicall(
                self.contract.encodeABI("decreaseLiquidity", args=[params]),
                self.contract.encodeABI("collect", args=[collect_params]),
            )

        result = self.transact_with_return(
            function, 
            trx_params,
            [self.contract.events.DecreaseLiquidity(), self.contract.events.Collect()],
        )
        return result

    def increaseLiquidity(self, token_id: int, amount0: int, amount1: int, min_pct: float=0, **trx_params) -> dict:
        """IncreaseLiquidity to a position

        Solidity documentation: 
            https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#increaseliquidity
            https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#increaseliquidityparams


        :param token_id: The ID of the token that represents the position
        :type token_id: int
        :param amount0: Amount of token0 to increase
        :type amount0: int
        :param amount1: Amount of token0 to increase
        :type amount1: int
        :param min_pct: [description], defaults to 0
        :type min_pct: float, optional
        :return: transation data
        :rtype: [type]

        >>> transation data:
            {
                events: [IncreaseLiquidityDict]
            }

        IncreaseLiquidityDict see: https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#increaseliquidity-1
        """
        params = dict(
            tokenId=token_id,
            amount0Desired=amount0,
            amount1Desired=amount1,
            amount0Min=int(amount0*min_pct),
            amount1Min=int(amount1*min_pct),
            deadline=int(datetime.now().timestamp() + 60)
        )
        is_eth, pos = self.eth_owed_in_position(token_id)

        if is_eth:
            function = self.multicall(
                self.contract.encodeABI("increaseLiquidity", [params]),
                self.contract.encodeABI("refundETH")
            )
            trx_params["value"] = amount1 if pos else amount0
        else:
            function = self.contract.get_function_by_name("increaseLiquidity")(params)
        
        if self.call_only:
            return {
                "trx_sent": False,
                "reason": "call only",
                "call_result": function.call(trx_params)
            }
        return self.transact_with_return(function, trx_params, [self.contract.events.IncreaseLiquidity()])
    
    def mint(
        self, token0: str, token1: str, amount0: int, amount1: int, tickLower: int, tickUpper: int, 
        fee: PoolFee=PoolFee.medium, min_pct: float=0,
        **trx_params
        ):

        params = dict(
            token0=token0,
            token1=token1,
            fee=fee.value,
            tickLower=int(tickLower-tickLower%60),
            tickUpper=int(tickUpper-tickUpper%60),
            amount0Desired=amount0,
            amount1Desired=amount1,
            amount0Min=int(amount0*min_pct),
            amount1Min=int(amount1*min_pct),
            recipient=self.account.address,
            deadline=int(datetime.now().timestamp() + self.default_deadline)
        )

        weth9 = self.weth9()
        if token0 == weth9:
            trx_params["value"] = amount0
            function = self.multicall(
                self.contract.encodeABI("mint", args=[params]),
                self.contract.encodeABI("refundETH"),
            )
        elif token1 == weth9:
            trx_params["value"] = amount1
            function = self.multicall(
                self.contract.encodeABI("mint", args=[params]),
                self.contract.encodeABI("refundETH"),
            )
        else:
            function = self.contract.get_function_by_name("mint")(params)
        if self.call_only:
            result = self.contract.get_function_by_name("mint")(params).call(trx_params)
            return {
                "trx_sent": False,
                "reason": "call only",
                "call_result": result
            }
        else:
            return self.transact_with_return(
                function, trx_params, 
                [
                    self.contract.events.IncreaseLiquidity(),
                    self.contract.events.Transfer(),

                ]
            )
    
    def get_pool_price(self, token0: str, token1: str, fee: PoolFee) -> float:
        pool = self.get_pool(token0, token1, fee)
        slot0 = pool.slot0()
        tick = slot0[1]
        return math.pow(1.0001, tick)

    def cal_increase_position(
        self, token0: Union[Tuple[str, int], str], token1: Union[Tuple[str, int], str],
        low_price: float, high_price: float, current_price: float=None, 
        amount0: Union[int, float]=None, amount1: Union[int, float]=None,
        fee: PoolFee=PoolFee.medium, price_reverted=False
        ) -> Tuple[int, int, int, int, int]:
        """Calculate params for mint and increaseLiqudity function.

        Price: p token1 per token0

        sample: 
            WETH: 
                address: 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
                decimal: 18
            USDT: 
                address: 0xdAC17F958D2ee523a2206206994597C13D831ec7
                decimal: 6

            address(WETH) < address(USDT)
            token0 = WETH
            token1 = USDT

            POOL: WETH/USDT
            PRICE(P): 
                P = token0 / token1 
                  = WETH / USDT
                  = value(1WETH) / value(1USDT)
            PRICE_IN_POOL(PIP):
                1 WETH = 1e18 WETHwei
                1 USDT = 1e6 USDTwei
                PIP = WETHwei / USDTwei
                    = 1e-18 WETH / 1e-6 USDT
                    = 1e-12 WETH / USDT
                    = 1e-12 P
            PRICE_TICK: 
                tick = log(PIP) / log(1.0001)



        :param token0: address and decimal of token0. Get decimal0 from rpc if token0 only provides address.
        :type token0: Tuple[str, int] or str
        :param token1: address and decimal of token1. Get decimal1 from rpc if token1 only provides address.
        :type token1: Tuple[str, int] or str
        :param current_price: current price of pool
        :type current_price: float
        :param low_price: Min price limit of the position
        :type low_price: float
        :param high_price: Max price limit of the position
        :type high_price: float
        :param amount0: amount of token0 to put, defaults to None
        :type amount0: Optional[int], optional
        :param amount1: amount of token0 to put, defaults to None
        :type amount1: Optional[int], optional
        :param fee: fee rate, defaults to PoolFee.medium
        :type fee: PoolFee, optional
        :param price_reverted: if True price = price(token0)/price(token1), defaults to False
        :type price_reverted: bool, optional
        :return: Tuple[liquidity, amount0, amount1, tickMin, tickMax]
        :rtype: Tuple[int, int, int, int, int]
        """

        assert amount0 or amount1, "Must input at least one param: amount0 or amount1"

        if isinstance(token0, tuple):
            token0, decimal0 = token0
        else:
            decimal0 = self.get_erc20_token(token0).decimals()

        if isinstance(token1, tuple):
            token1, decimal1 = token1
        else:
            decimal1 = self.get_erc20_token(token1).decimals()
        
        price_multipiler = 10**(decimal1-decimal0)
        if current_price:
            if price_reverted:
                current_price = 1 / current_price
            current_price = current_price * price_multipiler
        else:
            pool = self.get_pool(token0, token1, fee)
            slot0 = pool.slot0()
            tick = slot0[1]
            current_price = math.pow(1.0001, tick)
        

        if price_reverted:    
            low_price, high_price = 1/high_price, 1/low_price

        low_price = low_price * price_multipiler
        high_price = high_price * price_multipiler
        
        tickLower = int(math.log(low_price, 1.0001))
        tickhigher = int(math.log(high_price, 1.0001))

        if not amount1:
            # TODO: cal amount1
            amount0 = int(amount0 * 10**decimal0)
            liquidity, _, amount1 = self.cal_liquidity(current_price, high_price, low_price, amount0, amount1)
        elif not amount0: 
            # TODO: cal amount0
            amount1 = int(amount1 * 10**decimal1)
            liquidity, amount0, _ = self.cal_liquidity(current_price, high_price, low_price, amount0, amount1)
        else:
            amount0 = int(amount0 * 10**decimal0)
            amount1 = int(amount1 * 10**decimal1)

        return (liquidity, amount0, amount1, tickLower, tickhigher)




    def mint_by_price(
        self, token0: Union[Tuple[str, int], str], token1: Union[Tuple[str, int], str],
        low_price: float, high_price: float, current_price: float=None,
        amount0: Union[int, float]=None, amount1: Union[int, float]=None,
        fee: PoolFee=PoolFee.medium, min_pct: float=0, price_reverted=False,
        **trx_params
        ):
        """Mint a position and increase liquidity and get position token id.

        :param token0: address of token0
        :type token0: str
        :param token1: address of token1
        :type token1: str
        :param current_price: price(token1)/price(token0)
        :type current_price: float
        :param low_price: Min price limit of the position
        :type low_price: float
        :param high_price: Max price limit of the position
        :type high_price: float
        :param amount0: amount of token0 to put, defaults to None
        :type amount0: Optional[int], optional
        :param amount1: amount of token0 to put, defaults to None
        :type amount1: Optional[int], optional
        :param fee: fee rate, defaults to PoolFee.medium
        :type fee: PoolFee, optional
        :param min_pct: [description], defaults to 0
        :type min_pct: float, optional
        :param price_reverted: if True price = price(token0)/price(token1), defaults to False
        :type price_reverted: bool, optional
        :return: transaction data
        :rtype: [type]

        >>> transaction data
            {
                "events": [IncreaseLiquidityDict, TransferDict]
            }
        
        IncreaseLiquidityDict see: https://docs.uniswap.org/protocol/reference/periphery/interfaces/INonfungiblePositionManager#increaseliquidity-1
        
        """


        liquidity, amount0, amount1, tickLower, tickhigher = self.cal_increase_position(
            token0, token1, low_price, high_price, current_price, amount0, amount1, fee, price_reverted
        )

        if isinstance(token0, tuple):
            token0 = token0[0]
        
        if isinstance(token1, tuple):
            token1 = token1[0]

        return self.mint(
            token0, token1, int(amount0), int(amount1), 
            tickLower, tickhigher, fee, min_pct,
            **trx_params
        )
            
    def cal_liquidity(self, cprice: float, upper:float, lower: float, amt0: int, amt1: int):
        """

        Case 1: cprice <= lower
        liquidity = amt0 * (sqrt(upper) * sqrt(lower)) / (sqrt(upper) - sqrt(lower))
        Case 2: lower < cprice <= upper
        liquidity is the min of the following two calculations:
        amt0 * (sqrt(upper) * sqrt(cprice)) / (sqrt(upper) - sqrt(cprice))
        amt1 / (sqrt(cprice) - sqrt(lower))
        Case 3: upper < cprice
        liquidity = amt1 / (sqrt(upper) - sqrt(lower))

        :param cprice: [description]
        :type cprice: float
        :param upper: [description]
        :type upper: float
        :param lower: [description]
        :type lower: float
        :param amt0: [description]
        :type amt0: int
        :param amt1: [description]
        :type amt1: int
        """

        if cprice <= lower:
            assert amt0, f"When cprice({cprice}) <= lower({lower}), amt0 must bigger than 0"
            return int(
                amt0 * (math.sqrt(upper)*math.sqrt(lower)/(math.sqrt(upper)-math.sqrt(lower)))
            ), amt0, 0
        elif lower < cprice <= upper:
            if amt0:
                
                liquidity = int(
                    amt0 * (math.sqrt(upper) * math.sqrt(cprice)) / (math.sqrt(upper) - math.sqrt(cprice))
                )
                amt1 = int(
                    liquidity * (math.sqrt(cprice) - math.sqrt(lower))
                )
                return liquidity, amt0, amt1
            else:
                liquidity = int(
                    amt1 / (math.sqrt(cprice) - math.sqrt(lower))
                )
                amt0 = int(
                    liquidity * (math.sqrt(upper) - math.sqrt(cprice)) / (math.sqrt(upper) * math.sqrt(cprice))
                )
                return liquidity, amt0, amt1
        else:
            assert amt1, f"When upper({upper}) < cprice({cprice}), amt1 must bigger than 0"
            return int(
                amt1 / (math.sqrt(upper) - math.sqrt(lower))
            ), 0, amt1

    def multicall(self, *encodedABI):
        data = [bytes.fromhex(hexstr[2:]) for hexstr in encodedABI]
        return self.contract.get_function_by_name("multicall")(data)

    def nft_token(self, index: int=0):
        return self.contract.get_function_by_name("tokenOfOwnerByIndex")(
            self.account.address,
            index
        ).call()

    def nft_balance(self):
        return self.contract.get_function_by_name("balanceOf")(self.account.address).call()
    
    def nft_tokens(self) -> list:
        """Get nft tokens owned by this account

        :return: List[tokenIds]
        :rtype: list
        """
        balance = self.nft_balance()
        token_ids = []
        for i in range(balance):
            token_ids.append(self.nft_token(i))
        return token_ids

    def burn(self, token_id: int, **trx_params):
        function = self.contract.functions.burn(token_id)
        # return function.call()
        return self.transact_with_return(
            function, trx_params
        )



