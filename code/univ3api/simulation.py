from datetime import datetime
import math

from numpy import blackman
from .utils import PositionUtil
import pandas  as pd
from typing import Dict, Iterable, Tuple, Union, List
from .contracts.enums import PoolFee
from collections import namedtuple


V3FACTORY_CREATION_BLOCK = 12369621 

LiquidityLog = namedtuple("LiquidityLog", ["block", "timestamp", "liquidity"])
PositionBalanceLog = namedtuple("PositionBalanceLog",  ["block", "timestamp", "amount0", "amount1", "fee0", "fee1"])
WalletLog = namedtuple("WalletLog", ["block", "timestamp", "amount0", "amount1"])

DataEvent = namedtuple("DataEvent", ["timestamp", "priority", "data"])


def position_curve(pu: PositionUtil, prices: pd.DataFrame):
    pair_price = prices["token0"]/prices["token1"]
    positions = pd.DataFrame({
        "position0": pair_price.apply(pu.qty0),
        "position1": pair_price.apply(pu.qty1),
    })
    positions["mkv0"] = positions["position0"] * prices["token0"]
    positions["mkv1"] = positions["position1"] * prices["token1"]
    positions["mkv"] = positions["mkv0"] + positions["mkv1"]
    return positions


class PositionInstance(PositionUtil):

    def __init__(
        self, liquidity: Union[float, int], 
        tick_lower: int, tick_upper: int, 
        decimal0: int, decimal1: int, 
        fee_rate: int, token_id: int=0, price_reverse: bool=False) -> None:
        super().__init__(liquidity, tick_lower, tick_upper, decimal0=decimal0, decimal1=decimal1, price_reverse=price_reverse)
        self.fee_rate = fee_rate
        self.fee0 = 0
        self.fee1 = 0
        self.token_id = token_id
        self.balance: List[PositionBalanceLog] = []
        self.history: List[LiquidityLog] = []

    def increase_liquidity(self, sqrt_price: float, amount0: int, amount1: int) -> Tuple[int, int, int]:
        amt0 = self.amount0_psqrt(sqrt_price)
        amt1 = self.amount1_psqrt(sqrt_price)
        l, _, _ = self.cal_liquidity_sqrt(sqrt_price, self.low_price_sqrt, self.high_price_sqrt, amount0, amount1)
        liquidity = self.liquidity + l
        self.update_liquidity(liquidity)
        return l, self.amount0_psqrt(sqrt_price) - amt0, self.amount1_psqrt(sqrt_price) - amt1

    def decrease_liquidity(self, sqrt_price: float, liquidity: int=None, pct: float=1) -> Tuple[int, int, int]:
        assert liquidity or pct
        if not liquidity:
            assert 0 < pct <= 1
            liquidity = self.liquidity*pct  
        a0, a1 = self.amount0_psqrt(sqrt_price), self.amount1_psqrt(sqrt_price)
        self.update_liquidity(self.liquidity - liquidity)
        return self.liquidity, a0-self.amount0_psqrt(sqrt_price), a1-self.amount1_psqrt(sqrt_price)

    def swap(self, from_sqrt_price: float, to_sqrt_price: float) -> Tuple[int, int]:
        if to_sqrt_price > from_sqrt_price:
            amount1 = self.amount1_psqrt(to_sqrt_price) - self.amount1_psqrt(from_sqrt_price)
            fee1 = int(amount1*self.fee_rate/1000000)
            self.fee1 += fee1
            return 0, fee1
        else:
            amount0 = self.amount0_psqrt(to_sqrt_price) - self.amount0_psqrt(from_sqrt_price)
            fee0 = int(amount0*self.fee_rate/1000000)
            self.fee0 += fee0
            return fee0, 0
    
    def is_active(self, sqrt_price: float):
        return self.liquidity and self.low_price_sqrt <= sqrt_price <= self.high_price_sqrt

    def collect(self):
        f0, f1 = self.fee0, self.fee1
        self.fee0, self.fee1 = 0, 0
        return f0, f1
    
    def log_history(self, block: int, timestamp: int):
        self.history.append(LiquidityLog(block, timestamp, self.liquidity))
    
    def log_balance(self, block: int, timestamp: int, sqrt_price: float, fee0: int, fee1: int):
        self.balance.append(
            PositionBalanceLog(
                block, 
                timestamp,
                self.amount0_psqrt(sqrt_price),
                self.amount1_psqrt(sqrt_price),
                fee0,
                fee1 
            )
        )
    

class PositionReport(object):

    def __init__(self, position: PositionInstance) -> None:
        self.position = position
        self.balance = pd.DataFrame(position.balance)
        self.balance["collectedFee0"] = self.balance["fee0"].cumsum()
        self.balance["collectedFee1"] = self.balance["fee1"].cumsum()
        self.balance["cumFee0"] = self.balance["fee0"].apply(lambda f: f if f>=0 else 0).cumsum()
        self.balance["cumFee1"] = self.balance["fee1"].apply(lambda f: f if f>=0 else 0).cumsum()
        self.liquidity_history = pd.DataFrame(position.history)

    def get_balance(self, index="timestamp", plain=False, draw_plot=False):
        if plain:
            balance = self.plain_balance()
            index="datetime"
        else:
            balance = self.balance

        if draw_plot:
            for name in ["amount0", "cumFee0", "amount1", "cumFee1"]:
                balance.plot(x=index, y=name)
        return balance

    def plot_balance(self, index="timestamp", plain=False):
        if plain:
            balance = self.plain_balance()
            index="datetime"
        else:
            balance = self.balance

        for name in ["amount0", "cumFee0", "amount1", "cumFee1"]:
            balance.plot(x=index, y=name)
    
    def plain_balance(self):
        data = {}
        data["datetime"] = self.balance["timestamp"].apply(datetime.fromtimestamp)
        for token in [0, 1]:
            _d = self.position.decimals[token]
            factor = 10**_d
            for name in ["amount", "fee", "cumFee", "collectedFee"]:
                key = name + str(token)
                data[key] = self.balance[key] / factor

        balance = pd.DataFrame(data)

        return balance
        

class SimulationReport(object):

    def __init__(self, wallet_balance: pd.DataFrame, positions: Dict[int, PositionReport], info: Dict=None) -> None:
        self.wallet_balance = wallet_balance
        self.positions = positions
        self.info = info or {}

    def total_balance(self, index="timestamp", draw_plot=False, plain=False, **plot_params):
        balance = self.wallet_balance.drop_duplicates(index, keep="last").set_index(index)[["amount0", "amount1"]].astype("object")
            
        cumFee0 = pd.Series(0,  balance.index, dtype="object")
        cumFee1 = pd.Series(0,  balance.index, dtype="object")
        for report in self.positions.values():
            position_balance = report.balance.drop_duplicates(
                index, keep="last"
            ).set_index(index)[["amount0", "amount1", "fee0", "fee1", "collectedFee0", "collectedFee1"]].astype("object")
            amount0 = position_balance["amount0"] + position_balance["collectedFee0"]
            amount1 = position_balance["amount1"] + position_balance["collectedFee1"]
            
            balance["amount0"] += pd.Series(amount0, balance.index, dtype="object").fillna(0)
            balance["amount1"] += pd.Series(amount1, balance.index, dtype="object").fillna(0)

            cumFee0 += pd.Series(position_balance["fee0"][position_balance["fee0"]>=0].astype("object"), balance.index).fillna(0).astype("object").cumsum()
            cumFee1 += pd.Series(position_balance["fee1"][position_balance["fee1"]>=0].astype("object"), balance.index).fillna(0).astype("object").cumsum()
        balance["cumFee0"] = cumFee0
        balance["cumFee1"] = cumFee1
        balance["amount0NoFee"] = balance["amount0"] - balance["cumFee0"]
        balance["amount1NoFee"] = balance["amount1"] - balance["cumFee1"]
        balance.reset_index(inplace=True)
        if plain:
            index="datetime"
            balance = plain_balance(balance, self.info.get("decimal0", 0), self.info.get("decimal1", 0))

        if draw_plot:
            for name in ["amount0", "cumFee0", "amount1", "cumFee1"]:
                balance.plot(x=index, y=name, **plot_params)
        return balance            

   
def plain_balance(data: pd.DataFrame, decimal0: int, decimal1: int, keep: bool=True, excepts=None):
    r = {}
    r["datetime"] = data["timestamp"].apply(datetime.fromtimestamp)
    f0 = 10**decimal0
    f1 = 10**decimal1
    excepts = excepts or set()
    for column in data.columns:
        if column in excepts:
            continue
        if "0" in column:
            r[column] = data[column] / f0
        elif "1" in column:
            r[column] = data[column] / f1
        elif keep:
            r[column] = data[column]

    return pd.DataFrame(r)
    

class PoolSimiulation(object):

    PRICE_FACTOR = 1 << 96

    def __init__(self, amount0: int, amount1: int, decimal0: int, decimal1: int, fee: PoolFee, price_reverse: bool=False) -> None:
        """Init simulation

        :param amount0: Init amount of token0.
        :type amount0: int
        :param amount1: Init amount of token1.
        :type amount1: int
        :param decimal0: decimal of token0.
        :type decimal0: int
        :param decimal1: decimal of token1.
        :type decimal1: int
        :param fee: Fee of this strategy.
        :type fee: PoolFee
        """
        self.decimal0 = decimal0
        self.decimal1 = decimal1
        self.amount0 = amount0
        self.amount1 = amount1
        self.positions: Dict[int, PositionInstance] = {}
        self.valid_positions: Dict[int, PositionInstance] = {}
        self._next_token_id = 0
        self.fee = fee
        self.tick = 0
        self.sqrt_price_x96 = 0
        self.sqrt_price = 0
        self.block_number = 0
        self.timestamp = 0
        self.L = 0 
        self._price_reverse = price_reverse
        self.wallet_logs: List[WalletLog] = []
    
    def record_wallet(self):
        self.wallet_logs.append(WalletLog(self.block_number, self.timestamp, self.amount0, self.amount1))

    @property
    def next_token_id(self):
        self._next_token_id += 1
        return self._next_token_id

    def mint(self, lower: int, upper: int,  amount0: int, amount1: int) -> Tuple[PositionInstance, int, int]:
        # TODO: create a PositionInstance
        fee = self.fee
        lower = lower - lower % 60
        upper = upper - upper % 60

        assert self.amount0 >= amount0, f"Amount for token0 not enough, required={amount0}, holding={self.amount0}"
        assert self.amount1 >= amount1, f"Amount for token1 not enough, required={amount1}, holding={self.amount1}"

        l, amt0, amt1 = PositionUtil.cal_liquidity_sqrt(
            self.sqrt_price,
            1.0001 ** (lower/2),
            1.0001 ** (upper/2),
            amount0,
            amount1
        )
        
        position = PositionInstance(
            l, lower, upper, self.decimal0, self.decimal1, fee.value,
            self.next_token_id, self._price_reverse
        )
        amt0 = position.amount0_psqrt(self.sqrt_price)
        amt1 = position.amount1_psqrt(self.sqrt_price)
        self.amount0 -= amt0
        self.amount1 -= amt1
        self.positions[position.token_id] = position
        self.valid_positions[position.token_id] = position
        position.log_history(self.block_number, self.timestamp)
        position.log_balance(self.block_number, self.timestamp, self.sqrt_price, 0, 0)
        self.record_wallet()
        return position, amt0, amt1 

    def increase_liquidity(self, token_id: int, amount0: int, amount1: int) -> Tuple[PositionInstance, int, int]:
        # TODO: increase liquidity in a specific pool and return increased amounts 
        position = self.positions[token_id]
        org_l = position.liquidity
        l, amt0, amt1 = position.increase_liquidity(
            self.sqrt_price,
            amount0, amount1
        )

        try:
            assert self.amount0 >= amt0, f"Amount for token0 not enough, required={amt0}, holding={self.amount0}"
            assert self.amount1 >= amt1, f"Amount for token1 not enough, required={amt1}, holding={self.amount1}"
        except:
            position.update_liquidity(org_l)
            raise
        self.amount0 -= amt0
        self.amount1 -= amt1

        if position.token_id not in self.valid_positions:
            self.valid_positions[position.token_id] = position
        
        position.log_history(self.block_number, self.timestamp)
        position.log_balance(self.block_number, self.timestamp, self.sqrt_price, 0, 0)
        self.record_wallet()
        return position, amt0, amt1
        

    def decrease_liquidity(self, token_id: int, liquidity: int=None, pct: float=1) -> Tuple[int, int, int]:
        position = self.positions[token_id]
        l, amt0, amt1 = position.decrease_liquidity(self.sqrt_price, liquidity, pct)
        self.amount0 += amt0
        self.amount1 += amt1
        if position.liquidity == 0:
            self.valid_positions.pop(position.token_id, None)
        position.log_history(self.block_number, self.timestamp)
        self.record_wallet()
        return position, amt0, amt1
        
    def collect(self, token_id: int) -> Tuple[int, int]:
        position = self.positions[token_id]
        amt0, amt1 = position.collect()
        self.amount0 += amt0
        self.amount1 += amt1
        position.log_balance(
            self.block_number,
            self.timestamp,
            self.sqrt_price,
            -amt0,
            -amt1
        )
        self.record_wallet()
        return  amt0, amt1
    
    def init(self, swap_event: dict):
        """Init by block data by first swap event

        :param swap_event: [description]
        :type swap_event: dict
        """
        self.sqrt_price_x96 = int(swap_event["sqrtPriceX96"])
        self.tick = swap_event["tick"]
        self.block_number = swap_event["blockNumber"]
        self.sqrt_price = self.sqrt_price_x96 / self.PRICE_FACTOR
        self.timestamp = swap_event.get("timestamp", 0)
        self.L = swap_event["liquidity"]

    def on_swap(self, swap_event: dict):
        former_price = self.sqrt_price
        self.sqrt_price_x96 = int(swap_event["sqrtPriceX96"])
        self.tick = swap_event["tick"]
        self.block_number = swap_event["blockNumber"]
        self.L = swap_event["liquidity"]
        self.sqrt_price = self.sqrt_price_x96 / self.PRICE_FACTOR
        self.timestamp = swap_event.get("timestamp", 0)

        for position in self.valid_positions.values():
            fee0, fee1 = position.swap(former_price, self.sqrt_price)
            position.log_balance(
                self.block_number,
                self.timestamp,
                self.sqrt_price,
                fee0, fee1
            )
        self.record_wallet()
    
    def swap(self, in_token: int, amount: int=0, pct: float=0) -> int:
        """swap operation

        :param in_token: the token to trade in, 0 or 1
            0: spend token0 get token1
            1: spend token1 get token0
        :type in_token: int
        :param amount: the amount of in_token, defaults to 0
        :type amount: int, optional
        :param pct: the percetange of in_token to spend, defaults to 0
        :type pct: float, optional
        :raises ValueError: One of amount and pct should be greater than 0
        :raised AssertionError: Amount not enough for swap
        :return: target amount by swap
        :rtype: int
        """
        # swap token1 get token0
        if in_token:
            if not amount:
                if pct:
                    amount = int(self.amount1 * pct)
                else:
                    raise ValueError("amount or pct")
            total_amount = int(amount*(self.fee.value/1e6+1))
            assert self.amount1 > total_amount, f"Amount1 not enough: required={total_amount}, holding={self.amount1}"
            
            amount0 = int(self.L*(1/self.sqrt_price - self.L/(self.L*self.sqrt_price+amount)))
            self.amount0 += amount0
            self.amount1 -= total_amount
            return amount0
        # swap token0 get token1
        else:
            if not amount:
                if pct:
                    amount = int(self.amount0 * pct)
                else:
                    raise ValueError("amount or pct")
            total_amount = int(amount*(self.fee.value/1e6+1))
            assert self.amount0 > total_amount, f"Amount0 not enough: required={total_amount}, holding={self.amount0}"
            amount1 = int(self.L*(self.sqrt_price - self.L/(self.L/self.sqrt_price + amount)))
            self.amount1 += amount1
            self.amount0 -= total_amount    
            return amount1
    
            
    def run_on_swap(self, dfs: Iterable[pd.DataFrame]):
        for df in dfs:
            for swap in df.to_dict("record"):
                self.on_swap(swap)
    
    def run(self, swaps: pd.DataFrame, time_data: pd.DataFrame):
        """Run simulation base on parsed data

        :param swaps: SwapEvent data for simulation.
        :type swaps: pd.DataFrame
        :param time_data: Timeseries data which will be splitted ad data.to_dict("record") and parse into self.on_time(data) 
        :type time_data: pd.DataFrame

        swaps:
        >>>    blockNumber    amount0              amount1    tick   timestamp                        sqrtPriceX96
            0     12376891 -119744094    35000000000000000  194996  1620252901  1358206768703179146794161129278934
            1     12377278  499756414  -144241064315415179  194645  1620257875  1334545912983135722438993170925379
            2     12377345  365000000  -103492428467657963  194641  1620258696  1334315597745343730478188229716159
            3     12377364 -176180828    50000000000000000  194643  1620258994  1334426813649531849390742241713392
            4     12377369 -514279985   146000000000000000  194648  1620259056  1334751564089761156615399956745312

        time_data:
        >>>     timestamp                        sqrtPriceX96        price
            0  1620252901  1358206768703179146794161129278934  3402.729189
            1  1620257875  1334545912983135722438993170925379  3524.456285
            2  1620258696  1334315597745343730478188229716159  3525.673098
            3  1620258994  1334426813649531849390742241713392  3525.085438
            4  1620259056  1334751564089761156615399956745312  3523.370312


        """
        swap_events = swaps.to_dict("record").__iter__()
        time_list = time_data.to_dict("record").__iter__()

        swap = next(swap_events)
        data = next(time_list)
        while True:
            if (swap["timestamp"], 1) <= (data["timestamp"], 0):
                self.on_swap(swap)
                try:
                    swap = next(swap_events)
                except StopIteration:
                    for i in range(time_list.__length_hint__()):
                        self.on_time(next(time_list))
                    break
            else:
                self.on_time(data)
                try:
                    data = next(time_list)
                except StopIteration:
                    for i in range(swap_events.__length_hint__()):
                        self.on_swap(next(swap_events))
                    break
                
    
    def get_position(self, token_id: int) -> PositionInstance:
        return self.positions[token_id]
    
    def on_time(self, data: dict):
        """Timeseries data callback

        Algorithn code should be write in here.

        :param data: dict item generated by time_data.to_dict("record") parsed in self.run(swaps, time_data)
        :type data: dict
        """
        pass 
    
    def report(self) -> SimulationReport:
        """Report of simulation results.

        :return: [description]
        :rtype: SimulationReport
        """
        wallet_balance = pd.DataFrame(self.wallet_logs)
        positions: Dict[int, PositionReport] = {}
        for position in self.positions.values():
            positions[position.token_id] = PositionReport(position)
        
        info = {
            "decimal0": self.decimal0,
            "decimal1": self.decimal1
        }
        return SimulationReport(wallet_balance, positions, info)


class DataUtilMongoDB(object):

    """Util for reading SwapEvent data from Mongodb.

    Default uri: "mongodb://localhost:27017/ETHDATA"
    """

    SWAP_BIGINT_COLUMNS = ("amount0", "amount1", "liquidity", "sqrtPriceX96")

    def __init__(self, host: str="mongodb://localhost:27017/ETHDATA") -> None:
        from pymongo import MongoClient
        self.client =MongoClient(host)
        self.db = self.client.get_default_database()
        self.block = "block"
    
    def swap_by_time(self, name: str, start_ts: int=None, end_ts: int=None) -> pd.DataFrame:
        """Read swap events selected by timestamp range

        :param name: collection name
        :type name: str
        :param start_ts: start timestamp, defaults to None
        :type start_ts: int, optional
        :param end_ts: end timestamp, defaults to None
        :type end_ts: int, optional
        :return: [description]
        :rtype: pd.DataFrame
        """
        block_collection = self.db[self.block]
        if start_ts:
            start_block = block_collection.find_one({"timestamp": {"$gte": start_ts}}, sort=[("timestamp", 1)])["number"]
        else:
            start_block = None

        if end_ts:
            end_block = block_collection.find_one({"timestamp": {"$lte": end_ts}}, sort=[("timestamp", -1)])["number"]
        else:
            end_block = None
        
        return self.swap_by_block(name, start_block, end_block)

    def swap_by_block(self, name: str, start_block: int=None, end_block: int=None) -> pd.DataFrame:
        """Read swap events selected by blockNumber

        :param name: collection name
        :type name: str
        :param start_block: start block number, defaults to None
        :type start_block: int, optional
        :param end_block: end block number, defaults to None
        :type end_block: int, optional
        :return: SwapEventsDataFrame
        :rtype: pd.DataFrame
        """
        filters = {}
        if start_block:
            filters["blockNumber"] = {"$gte": start_block}
        if end_block:
            filters.setdefault("blockNumber", {})["$lte"] = end_block
        collection = self.db[name]
        cursor = collection.find(
            filters,
            projection={"_id": 0}
        )
        data = pd.DataFrame(list(cursor))
        for key in self.SWAP_BIGINT_COLUMNS:
            data[key] = data[key].apply(int)
        
        blocks = self.blocks(list(data["blockNumber"]))
        block_map = {block["number"]: block["timestamp"] for block in blocks}
        data["timestamp"] = data["blockNumber"].map(block_map)
        return data
    
    def blocks(self, numbers: List[int]) -> List[Dict]:
        """Get list of block info containing blockNumber and timestamp

        :param numbers: list of blockNumber required.
        :type numbers: List[int]
        :return: List[{"number": number value, "timestamp": timestamp}]
        :rtype: List[Dict]
        """
        cursor = self.db[self.block].find(
            {"number": {"$in": numbers}},
            projection={"number": 1, "timestamp": 1}
        )
    
        return list(cursor)

