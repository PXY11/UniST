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
        self.openPosTimeList = [1622000000]
        
    def price_in_range(self, price):
        return self.lower_price < price < self.upper_price

    def cal_tick(self, upperTick, lowerTick):
        upper_tick = upperTick - upperTick % 60
        lower_tick = lowerTick - lowerTick % 60
        return upper_tick, lower_tick
    
    def on_time(self, data: dict):
        price = data["price"]
        ts = data["timestamp"]
        # trend = data['trend']
        SmaLowerLma = data['SmaLowerLma']
        VolLowerBelowmaQuantile50 = data['VolLowerBelowmaQuantile50']
        CloseLowerMA = data['CloseLowerMA']
        VolHigherOvermaQuantile50Twosigma = data['VolHigherOvermaQuantile50Twosigma']
        revoke_pos = data['revoke_pos']
        arRollNorm = data['arRollNorm']
        openTimeGap = self.timestamp - self.openPosTimeList[-1]
        '''
        建池条件检查
        '''
        if CloseLowerMA==True and SmaLowerLma==True and VolLowerBelowmaQuantile50==True and arRollNorm<5 and openTimeGap>=43200 and not self.position_id:
        # if CloseLowerMA==1 and SmaLowerLma==1  and not self.position_id:
            self.open_pos_times += 1
            self.short_pos = True
            print(f'**********************【Price Below MA】【创建Short Vol池子】【第{self.open_pos_times}次建池】***********************************')
            # self.upper_price = price*(1 + 4*0.026427*sqrt(self.day_length))
            # self.lower_price = price*(1 - 4*0.026427*sqrt(self.day_length))
            self.upper_price = price*(1 + 0.5)
            self.lower_price = price*(1 - 0.5)
            self.swap(0, pct=0.55)   #部分btc换成eth
            print('转换后钱包中余额','amount0: ', self.amount0, 'amount1: ',self.amount1)
            print("price: ", price)
            tick = self.pc.price_to_tick(price)
            upperTick = self.pc.price_to_tick(self.upper_price)
            lowerTick = self.pc.price_to_tick(self.lower_price)
            # (1)
            print('$$$$$$$【Upper Price】:', self.upper_price)
            print('$$$$$$$【Lower Price】:', self.lower_price)
            
            if self.price_in_range(price):
                upper_tick, lower_tick = self.cal_tick(upperTick, lowerTick)
                # cal L
                L, amount0, amount1 = utils.PositionUtil.cal_liquidity(
                                    cprice=1.0001**tick,
                                    upper=1.0001**upper_tick,
                                    lower=1.0001**lower_tick,
                                    amt0=int(self.amount0),
                                    amt1=None
                                )
                # print('######:', L, amount0, amount1)
                print('######【L】:{}【BTC】:{}【ETH】:{}'.format( L, amount0, amount1))
                pu = utils.PositionUtil(
                                        L,
                                        tick_lower=lower_tick,
                                        tick_upper=upper_tick,
                                        decimal0=6, ########注意币种转换区分########
                                        decimal1=18 ########注意币种转换区分########
                                        )
                t0 = pu.amount0_t(tick)
                t1 = pu.amount1_t(tick)
                # self.amount0 = t0
                # self.amount1 = t1

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
                self.openPosTimeList.append(self.timestamp)
                return


        elif CloseLowerMA==False and VolHigherOvermaQuantile50Twosigma==False and arRollNorm<5 and openTimeGap>=43200 and not self.position_id:
            self.open_pos_times += 1
            self.long_pos = True
            print(f'**********************【Price Over MA】【创建Long Vol池子】【第{self.open_pos_times}次建池】***********************************')
            
            # self.lower_price = price*(1 - 4*0.020494*sqrt(self.day_length))
            self.lower_price = price*(1 - 2*0.020494*sqrt(self.day_length))
            self.upper_price = price/self.lower_price*price 
            self.swap(0, pct=0.55)   #部分btc换成eth
            print('转换后钱包中余额','amount0: ', self.amount0, 'amount1: ',self.amount1)
            print("price: ", price)
            tick = self.pc.price_to_tick(price)
            upperTick = self.pc.price_to_tick(self.upper_price)
            lowerTick = self.pc.price_to_tick(self.lower_price)
            # (1)
            print('$$$$$$$【Upper Price】:', self.upper_price)
            print('$$$$$$$【Lower Price】:', self.lower_price)
            
            if self.price_in_range(price):
                upper_tick, lower_tick = self.cal_tick(upperTick, lowerTick)
                # cal L
                L, amount0, amount1 = utils.PositionUtil.cal_liquidity(
                                    cprice=1.0001**tick,
                                    upper=1.0001**upper_tick,
                                    lower=1.0001**lower_tick,
                                    amt0=int(self.amount0),
                                    amt1=None
                                )
                # print('######:', L, amount0, amount1)
                print('######【L】:{}【BTC】:{}【ETH】:{}'.format( L, amount0, amount1))
                pu = utils.PositionUtil(
                                        L,
                                        tick_lower=lower_tick,
                                        tick_upper=upper_tick,
                                        decimal0=6, ########注意币种转换区分########
                                        decimal1=18 ########注意币种转换区分########
                                        )
                t0 = pu.amount0_t(tick)
                t1 = pu.amount1_t(tick)
                # self.amount0 = t0
                # self.amount1 = t1

                print('将要投入池子的数量','amount_t0:', t0, 'amount_t1:', t1)
                # print('$$$$$$$$$$$$$$$$', self.amount1-t1)
                position, amt0, amt1 = self.mint(
                    lower_tick, upper_tick,
                    int(t0), int(t1)
                )
                self.position_id = position.token_id
                time_to_print = time.localtime(self.timestamp)
                time_to_print = time.strftime('%Y-%m-%d %H:%M:%S', time_to_print) #把struct time转str
                print(f"【RealWorldTime】:{time_to_print}, Timestamp: {self.timestamp}, Blocknumber: {self.block_number}")
                print(f"Mint position： {position}")
                print(f"【Mint amount】: token0={amt0/self.factor0}, token1={amt1/self.factor1}")
                print(f"Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
                self.mint_price = price
                self.mint_timestamp = ts
                self.openPosTimeList.append(self.timestamp)
                return
        '''
        撤池条件检查
        '''
        if (not( CloseLowerMA==False and VolHigherOvermaQuantile50Twosigma==False or revoke_pos==False) or arRollNorm>=5) and self.long_pos==True :
            # if self.position_id and not self.price_in_range(price):
            print('******************************************【撤销池子】【原因:OverMA与VolHigherQuantile50TwoSigma条件不满足】****************************')
            print(f'CloseLowerMA: {CloseLowerMA}, VolHigherQuantile50TwoSigma: {VolHigherOvermaQuantile50Twosigma},arRollNorm:{arRollNorm}')
            print(f"Price({price}) out of range({self.lower_price}, {self.upper_price})")
            position, amt0, amt1 = self.decrease_liquidity(self.position_id, pct=1)

            # self.short_pos =False
            self.long_pos = False
            time_to_print = time.localtime(self.timestamp)
            time_to_print = time.strftime('%Y-%m-%d %H:%M:%S', time_to_print)
            print(f"【RealWorldTime】:{time_to_print},Timestamp: {self.timestamp}, Blocknumber: {self.block_number}")
            print(f"Decreased position： {position}")
            print(f"【Decreased amount】: token0={amt0/self.factor0}, token1={amt1/self.factor1}")
            print(f"Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
            self.collect(self.position_id)
            self.position_id = None
            self.increased = False

            token1 = self.amount1/self.factor1
            if token1 > 0.05: #如果钱包里的eth多于0.05，则将eth全都换成btc
                self.swap(1,pct=0.95)
            print(f"撤池后经转换 Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
            return
        elif  (not(CloseLowerMA==True and SmaLowerLma==True and VolLowerBelowmaQuantile50==True) or arRollNorm>=5) and self.short_pos==True:
        # elif  not( SmaLowerLma==1) and self.short_pos==True:
            print('******************************************【撤销池子】【原因:BelowMA与SmaLowerLma与VolLowerQuantile75条件不满足】**********************')
            print(f'CloseLowerMA: {CloseLowerMA}, SmaLowerLma: {SmaLowerLma}, VolLowerQuantile75: {VolLowerBelowmaQuantile50},arRollNorm:{arRollNorm}')
            print(f"Price({price}) out of range({self.lower_price}, {self.upper_price})")
            position, amt0, amt1 = self.decrease_liquidity(self.position_id, pct=1)

            self.short_pos =False
            # self.long_pos = False
            time_to_print = time.localtime(self.timestamp)
            time_to_print = time.strftime('%Y-%m-%d %H:%M:%S', time_to_print)
            print(f"【RealWorldTime】:{time_to_print},Timestamp: {self.timestamp}, Blocknumber: {self.block_number}")
            print(f"Decreased position： {position}")
            print(f"【Decreased amount】: token0={amt0/self.factor0}, token1={amt1/self.factor1}")
            print(f"Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
            self.collect(self.position_id)
            self.position_id = None
            self.increased = False

            token1 = self.amount1/self.factor1
            if token1 > 0.05: #如果钱包里的eth多于0.05，则将eth全都换成btc
                self.swap(1,pct=0.99999)
            print(f"撤池后经转换 Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
            return
         
        if self.position_id and not self.price_in_range(price):
            print('******************************************【撤销池子】【原因:超边撤池】******************************************')
            print(f"Price({price}) out of range({self.lower_price}, {self.upper_price})")
            position, amt0, amt1 = self.decrease_liquidity(self.position_id, pct=1)

            self.short_pos =False
            self.long_pos = False
            time_to_print = time.localtime(self.timestamp)
            time_to_print = time.strftime('%Y-%m-%d %H:%M:%S', time_to_print)
            print(f"【RealWorldTime】:{time_to_print},Timestamp: {self.timestamp}, Blocknumber: {self.block_number}")
            print(f"Decreased position： {position}")
            print(f"【Decreased amount】: token0={amt0/self.factor0}, token1={amt1/self.factor1}")
            print(f"Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
            self.collect(self.position_id)
            self.position_id = None
            self.increased = False

            token1 = self.amount1/self.factor1
            if token1 > 0.05: #如果钱包里的eth多于0.05，则将eth全都换成btc
                self.swap(1,pct=0.95)
            print(f"撤池后经转换 Wallet amount: token0={self.amount0/self.factor0}, token1={self.amount1/self.factor1}")
            return
                