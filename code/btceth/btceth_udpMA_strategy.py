from math import sqrt
from univ3api.simulation import PoolSimiulation, PositionInstance, PoolFee
import univ3api.utils as utils
import numpy as np
from datetime import datetime
import time

class HoldStrategy(PoolSimiulation):
    def __init__(self, amount0: int, amount1: int, decimal0: int, decimal1: int, fee: PoolFee, price_reverse: bool=False) -> None:
        super().__init__(amount0, amount1, decimal0, decimal1, fee, price_reverse)
        self.position_id = None
        self.increased = False
        self.mint_price = 0
        self.mint_timestamp = 0
        self.factor0 = 10**self.decimal0
        self.factor1 = 10**self.decimal1
        self.pc = utils.PriceConverter(8, 18)
        self.open_pos_times = 0
        self.long_pos = False
        self.short_pos = False
        self.day_length = 30

    def price_in_range(self, price):
        return self.lower_price < price < self.upper_price

    def cal_tick(self, upperTick, lowerTick):
        upper_tick = upperTick - upperTick % 60
        lower_tick = lowerTick - lowerTick % 60
        return upper_tick, lower_tick

    def on_time(self, data: dict):
        price = data["price"]
        ts = data["timestamp"]
        udp = data["udp"]
        btcCLOSEoverMA = data["btcCLOSEoverMA"]
        ethCLOSEoverMA = data["ethCLOSEoverMA"]
        '''
        建池条件检查
        '''
        if btcCLOSEoverMA==True and ethCLOSEoverMA==True and udp>0 and not self.position_id:

            self.open_pos_times += 1
            print(f'**********************【创建long池子】【第{self.open_pos_times}次建池】**********************')
            self.upper_price = price*(1 + 0.5)
            self.lower_price = price*(1 - 0.5)
            self.swap(0,pct=0.7)
            print('转换后钱包中余额','amount0: ', self.amount0, 'amount1: ',self.amount1)
            print("price: ", price)
            tick = self.pc.price_to_tick(price)
            upperTick = self.pc.price_to_tick(self.upper_price)
            lowerTick = self.pc.price_to_tick(self.lower_price)
            print('$$$$$$$【Upper Price】:', self.upper_price)
            print('$$$$$$$【Lower Price】:', self.lower_price)
            if self.price_in_range(price):
                upper_tick, lower_tick = self.cal_tick(upperTick, lowerTick)
                L, amount0, amount1 = utils.PositionUtil.cal_liquidity(
                                    cprice=1.0001**tick,
                                    upper=1.0001**upper_tick,
                                    lower=1.0001**lower_tick,
                                    amt0=int(self.amount0),
                                    amt1=None
                                )
                print('######【L】:{}【BTC】:{}【ETH】:{}'.format( L, amount0, amount1))
                pu = utils.PositionUtil(
                                        L,
                                        tick_lower=lower_tick,
                                        tick_upper=upper_tick,
                                        decimal0=8, ########注意币种转换区分########
                                        decimal1=18 ########注意币种转换区分########
                                        )
                t0 = pu.amount0_t(tick)
                t1 = pu.amount1_t(tick)

                print('将要投入池子的数量','amount_t0:', t0, 'amount_t1:', t1)
                # print('$$$$$$$$$$$$$$$$', self.amount1-t1)
                position, amt0, amt1 = self.mint(
                    lower_tick, upper_tick,
                    int(t0), int(t1)
                )
                self.position_id = position.token_id
                time_to_print = time.localtime(self.timestamp)
                time_to_print = time.strftime('%Y-%m-%d %H:%M:%S', time_to_print)
                print(f"【RealWorldTime】:{time_to_print}, Timestamp: {self.timestamp}, Blocknumber: {self.block_number}")
                print(f"Mint position： {position}")
                print(f"【Mint amount】: token0={amt0/self.factor0}, token1={amt1/self.factor1}")
                print(f"Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
                self.mint_price = price
                self.mint_timestamp = ts
                return

        

