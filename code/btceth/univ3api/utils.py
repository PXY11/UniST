import math
from typing import Union
import warnings


class PositionUtil:
    """
    L = liquidity = sqrt(K^2)
    Pc = price on cex
    Pd = price on dex
    Tu, Tl = tick_upper, tick_lower
    d0, d1 = decimal0, decimal1
    
    token0 = (10**d0)w0
    token1 = (10**d0)w1

    Pc = token0 / token1
          = (10**d0)w0 / (10**d1)w1
    
    Pd = Pc * 10**(d1-d0) = w0/w1 = 1.0001^tick
    Pu = 1.0001^Tu
    Pl = 1.0001^Tl

    when Tl < tick < Tu:
        amount0 = L * (1/sqrt(Pd) - 1/sqrt(Pu))
                = L * (1.0001^(-tick/2) - 1.0001^(-Tu/2))
        amount1 = L * (sqrt(Pd) - sqrt(Pl))
                = L * (1.0001^(tick/2) - 1.0001^(Tl/2))
    
    when tick <= Tl:
        amount1 = 0
        amount0 = L * (1/sqrt(Pl) - 1/sqrt(Pu))
                = L * (1.0001^(-Tl/2) - 1.0001^(-Tu/2))
    
    when tick >= Tu:
        amount0 = 0
        amount1 = L * (sqrt(Pu) - sqrt(Pl))
                = L * (1.0001^(Tu/2) - 1.0001^(Tl/2))


    qty0 = amount0 * 1e-d0
    qty1 = amount1 * 1e-d1

    """

    def __init__(
            self, liquidity: Union[float, int], tick_lower: int, tick_upper: int,
            decimal0: int = 0, decimal1: int = 0, price_reverse: bool = False
    ) -> None:
        """Position util for calculating exporsure.

        `liquidity`, `tick_lower` and `tick_upper` can be achieved by calling `NonfungiblePositionManager.positions`
        tick_lower, tick_upper, liquidity = NonfungiblePositionManager.positions()[5, 6, 7]
        
        see: https://docs.uniswap.org/protocol/reference/periphery/NonfungiblePositionManager#positions
        
        :param liquidity: liquidity of current position
        :type liquidity: Union[float, int]
        :param tick_lower: low tick of current position
        :type tick_lower: int
        :param tick_upper: high tick of current position
        :type tick_upper: int
        :param decimal0: decimal of token0, defaults to 0
        :type decimal0: int, optional
        :param decimal1: decimal of token1, defaults to 0
        :type decimal1: int, optional
        """
        assert tick_lower < tick_upper, "Edge should be: tick_lower < tick_upper"
        assert tick_lower % 60 == 0, f"Invalid tick_lower: {tick_lower}, tick % 60 should be 0"
        assert tick_upper % 60 == 0, f"Invalid tick_upper: {tick_upper}, tick % 60 should be 0"
        self.liquidity = liquidity
        self.tick_lower = tick_lower
        self.tick_upper = tick_upper
        self.low_price_sqrt = 1.0001 ** (tick_lower / 2)
        self.low_price_sqrt_r = 1 / self.low_price_sqrt
        self.high_price_sqrt = 1.0001 ** (tick_upper / 2)
        self.high_price_sqrt_r = 1 / self.high_price_sqrt
        self._amount0_edge = 0
        self._amount1_edge = 0
        self.update_liquidity(liquidity)
        self.decimal0 = decimal0
        self.decimal1 = decimal1
        self.decimals = (decimal0, decimal1)
        self.factor0 = 10 ** -decimal0
        self.factor1 = 10 ** -decimal1
        self.factor = 10 ** (decimal1 - decimal0)
        pc = PriceConverter(decimal0, decimal1)
        if not price_reverse:
            self.cex_price_lower = pc.tick_to_price(self.tick_lower)
            self.cex_price_upper = pc.tick_to_price(self.tick_upper)
        else:
            self.cex_price_lower = pc.tick_to_price(self.tick_upper, price_reverse)
            self.cex_price_upper = pc.tick_to_price(self.tick_lower, price_reverse)

    @classmethod
    def mint(
        cls, tick_now: int, tick_lower: int, tick_upper: int, 
        amount0: int=0, amount1: int=0,
        decimal0: int = 0, decimal1: int = 0
        ):

        liquidity, _, _ = cls.cal_liquidity(
            1.0001 ** tick_now,
            1.0001 ** tick_upper,
            1.0001 ** tick_lower,
            amount0,
            amount1
        )
        return cls(liquidity, tick_lower, tick_upper, decimal0, decimal1)

    @classmethod
    def mint_by_price(
        cls, price: float, price_lower: float, price_upper: float, 
        qty0: float, qty1: float,
        decimal0: int = 0, decimal1: int = 0,
        reverted=False,
    ):
        if reverted:
            price = 1 / price,
            price_lower, price_upper = 1 / price_upper, 1 / price_lower
        factor = 10**(decimal1-decimal0)
        price = price* factor
        price_upper = price_upper* factor
        price_upper = price_upper* factor
        liquidity, _, _ = cls.cal_liquidity(
            price,
            price_upper,
            price_lower,
            qty0*10**decimal0,
            qty1*10**decimal1
        )
        tick_lower = math.log(price_lower, 1.0001)
        tick_upper = math.log(price_upper, 1.0001)
        return cls(liquidity, tick_lower, tick_upper, decimal0, decimal1)

    def update_liquidity(self, liquidity: Union[float, int]):
        self.liquidity = liquidity
        self._amount0_edge = int(self.liquidity * (self.low_price_sqrt_r - self.high_price_sqrt_r))
        self._amount1_edge = int(self.liquidity * (self.high_price_sqrt - self.low_price_sqrt))

    def amount0_t(self, tick: int) -> Union[int, float]:
        """Calculate amount0 by price tick.

        `tick` can be achieved by calling `UniswapV3Pool.slot0`
        tick = UniswapV3Pool.slot0()[1]

        see: https://docs.uniswap.org/protocol/reference/core/interfaces/pool/IUniswapV3PoolState#slot0

        :param tick: price tick
        :type tick: int
        :return: amount0
        :rtype: Union[int, float]
        """
        if tick <= self.tick_lower:
            return self._amount0_edge
        elif tick < self.tick_upper:
            return int(self.liquidity * (1.0001 ** (-tick / 2) - self.high_price_sqrt_r))
        else:
            return 0

    def amount1_t(self, tick: int) -> Union[int, float]:
        """Calculate amount1 by price tick

        `tick` can be achieved by calling `UniswapV3Pool.slot0`
        tick = UniswapV3Pool.slot0()[1]

        see: https://docs.uniswap.org/protocol/reference/core/interfaces/pool/IUniswapV3PoolState#slot0

        :param tick: price tick
        :type tick: int
        :return: amount1
        :rtype: Union[int, float]
        """
        if tick <= self.tick_lower:
            return 0
        elif tick < self.tick_upper:

            return int(self.liquidity * (1.0001 ** (tick / 2) - self.low_price_sqrt))
        else:
            return self._amount1_edge

    def amount0_psqrt(self, psqrt: float) -> Union[int, float]:
        """Calculate amount0 by sqaurt of price on chain

        psqrt = 1.0001**(tick/2)
              = (cexPrice*10**(decimal1-decimal0))**(1/2)
              = UniswapV3Pool.slot0()[0] * 2**-96

        :param psqrt: sqaurt of price on chain
        :type psqrt: float
        :return: amount0
        :rtype: Union[int, float]
        """
        if psqrt <= self.low_price_sqrt:
            return self._amount0_edge
        elif psqrt < self.high_price_sqrt:
            return int(self.liquidity * (1 / psqrt - self.high_price_sqrt_r))
        else:
            return 0

    def amount1_psqrt(self, psqrt: float) -> Union[int, float]:
        """Calculate amount1 by sqaurt of price on chain

        psqrt = 1.0001**(tick/2)
              = (cexPrice*10**(decimal1-decimal0))**(1/2)
              = UniswapV3Pool.slot0()[0] * 2**-96

        :param psqrt: sqaurt of price on chain
        :type psqrt: float
        :return: amount1
        :rtype: Union[int, float]
        """
        if psqrt <= self.low_price_sqrt:
            return 0
        elif psqrt < self.high_price_sqrt:

            return int(self.liquidity * (psqrt - self.low_price_sqrt))
        else:
            return self._amount1_edge

    def exposure0(self, price: float, reverted=False):
        """Calculate exposure of token0 by cex price
        
        Deprecated. Use qty0 instead.

        :param price: cex price
        :type price: float
        :param reverted: True if price=token1/token0, defaults to False
        :type reverted: bool, optional
        :return: expected exposure of token0 on cex 
        :rtype: [type]
        """
        warnings.warn("Function exposure0 is deprecated, use qty0 instead.")

        if reverted:
            price = 1 / price

        return self.amount0_psqrt(math.sqrt(price * self.factor)) * self.factor0

    def exposure1(self, price: float, reverted=False):
        """Calculate exposure of token0 by cex price

        Deprecated. Use qty1 instead.
        
        :param price: cex price
        :type price: float
        :param reverted: True if price=token1/token0, defaults to False
        :type reverted: bool, optional
        :return: expected exposure of token1 on cex 
        :rtype: [type]
        """
        warnings.warn("Function exposure1 is deprecated, use qty1 instead.")

        if reverted:
            price = 1 / price

        return self.amount1_psqrt(math.sqrt(price * self.factor)) * self.factor1

    def qty0(self, price: float, reverted=False):
        """Calculate quantity (amount in cex) of token0 by cex price
        
        :param price: cex price
        :type price: float
        :param reverted: True if price=token1/token0, defaults to False
        :type reverted: bool, optional
        :return: expected exposure of token0 on cex 
        :rtype: [type]
        """
        if reverted:
            price = 1 / price

        return self.amount0_psqrt(math.sqrt(price * self.factor)) * self.factor0

    def qty1(self, price: float, reverted=False):
        """Calculate quantity (amount in cex) of token0 by cex price
        
        :param price: cex price
        :type price: float
        :param reverted: True if price=token1/token0, defaults to False
        :type reverted: bool, optional
        :return: expected exposure of token1 on cex 
        :rtype: [type]
        """
        if reverted:
            price = 1 / price

        return self.amount1_psqrt(math.sqrt(price * self.factor)) * self.factor1

    @staticmethod
    def cal_liquidity_sqrt(sqrt_price: float, sqrt_lower: float, sqrt_upper: float, amt0: int, amt1: int):
        """
        Case 1: cprice <= lower
        liquidity = amt0 * (sqrt(upper) * sqrt(lower)) / (sqrt(upper) - sqrt(lower))
        Case 2: lower < cprice <= upper
        liquidity is the min of the following two calculations:
        amt0 * (sqrt(upper) * sqrt(cprice)) / (sqrt(upper) - sqrt(cprice))
        amt1 / (sqrt(cprice) - sqrt(lower))
        Case 3: upper < cprice
        liquidity = amt1 / (sqrt(upper) - sqrt(lower))


        :param sqrt_price: [description]
        :type sqrt_price: float
        :param sqrt_lower: [description]
        :type sqrt_lower: float
        :param sqrt_upper: [description]
        :type sqrt_upper: float
        :param amt0: [description]
        :type amt0: int
        :param amt1: [description]
        :type amt1: int
        :return: [description]
        :rtype: [type]
        """

        if sqrt_price <= sqrt_lower:
            assert amt0, f"When cprice({sqrt_price}) <= lower({sqrt_lower}), amt0 must bigger than 0"
            return int(
                amt0 * (sqrt_upper * sqrt_lower / (sqrt_upper - sqrt_lower))
            ), amt0, 0

        elif sqrt_price <= sqrt_upper:
            assert amt0 or amt1
            l0 = math.inf
            l1 = math.inf
            if amt0:

                l0 = int(
                    amt0 * (sqrt_upper * sqrt_price) / (sqrt_upper - sqrt_price)
                )

            if amt1:
                l1 = int(
                    amt1 / (sqrt_price - sqrt_lower)
                )
            if l0 < l1:
                amt1 = int(
                    l0 * (sqrt_price - sqrt_lower)
                )
                return l0, amt0, amt1
            else:
                amt0 = int(
                    l1 * (sqrt_upper - sqrt_price) / (sqrt_upper * sqrt_price)
                )
                return l1, amt0, amt1

        # Case 3: upper < cprice
        # liquidity = amt1 / (sqrt(upper) - sqrt(lower))
        else:
            assert amt1, f"When upper({sqrt_upper}) < cprice({sqrt_price}), amt1 must bigger than 0"
            return int(
                amt1 / (sqrt_upper - sqrt_lower)
            ), 0, amt1

    @staticmethod
    def cal_liquidity(cprice: float, upper: float, lower: float, amt0: int, amt1: int):
        """

        Case 1: cprice <= lower
        liquidity = amt0 * (sqrt(upper) * sqrt(lower)) / (sqrt(upper) - sqrt(lower))
        Case 2: lower < cprice <= upper
        liquidity is the min of the following two calculations:
        amt0 * (sqrt(upper) * sqrt(cprice)) / (sqrt(upper) - sqrt(cprice))
        amt1 / (sqrt(cprice) - sqrt(lower))
        Case 3: upper < cprice
        liquidity = amt1 / (sqrt(upper) - sqrt(lower))

        :param cprice: current price on chain
        :type cprice: float
        :param upper: upper price on chain
        :type upper: float
        :param lower: low price on chain
        :type lower: float
        :param amt0: amount of token0
        :type amt0: int
        :param amt1: amount of token1
        :type amt1: int
        """

        
        # Case 1: cprice <= lower
        # liquidity = amt0 * (sqrt(upper) * sqrt(lower)) / (sqrt(upper) - sqrt(lower))
        if cprice <= lower:
            assert amt0, f"When cprice({cprice}) <= lower({lower}), amt0 must bigger than 0"
            return int(
                amt0 * (math.sqrt(upper) * math.sqrt(lower) / (math.sqrt(upper) - math.sqrt(lower)))
            ), amt0, 0

        # Case 2: lower < cprice <= upper
        # liquidity is the min of the following two calculations:
        # amt0 * (sqrt(upper) * sqrt(cprice)) / (sqrt(upper) - sqrt(cprice))
        # amt1 / (sqrt(cprice) - sqrt(lower))
        elif cprice <= upper:
            assert amt0 or amt1
            l0 = math.inf
            l1 = math.inf
            if amt0:

                l0 = int(
                    amt0 * (math.sqrt(upper) * math.sqrt(cprice)) / (math.sqrt(upper) - math.sqrt(cprice))
                )

            if amt1:
                l1 = int(
                    amt1 / (math.sqrt(cprice) - math.sqrt(lower))
                )
            if l0 < l1:
                amt1 = int(
                    l0 * (math.sqrt(cprice) - math.sqrt(lower))
                )
                return l0, amt0, amt1
            else:
                amt0 = int(
                    l1 * (math.sqrt(upper) - math.sqrt(cprice)) / (math.sqrt(upper) * math.sqrt(cprice))
                )
                return l1, amt0, amt1

        # Case 3: upper < cprice
        # liquidity = amt1 / (sqrt(upper) - sqrt(lower))
        else:
            assert amt1, f"When upper({upper}) < cprice({cprice}), amt1 must bigger than 0"
            return int(
                amt1 / (math.sqrt(upper) - math.sqrt(lower))
            ), 0, amt1

    def __str__(self) -> str:
        return f"Position(L={self.liquidity}, tick=[{self.tick_lower}, {self.tick_upper}], range=[{self.cex_price_lower:.4f}, {self.cex_price_upper:.4f}])"


class PriceConverter(object):
    """Util for converting sqrtPriceX96 to readable cex price.


    Pool: ETH/USDT
        decimal0 = 18
        decimal1 = 6
        price = PriceConverter(18, 6).x96_to_price(sqrtPriceX96)
        dex_price = PriceConverter(18, 6).price_to_dex(price)
        tick = PriceConverter(18, 6).price_to_tick(price)
        sqrtPriceX96 = PriceConverter(18, 6).price_to_x96(price)

    Pool: USDC/ETH
        decimal0 = 6
        decimal1 = 18
        price = PriceConverter(6, 18).x96_to_price(sqrtPriceX96, True)
        dex_price = PriceConverter(6, 18).price_to_dex(price, True)
        tick = PriceConverter(6, 18).price_to_tick(price, True)
        sqrtPriceX96 = PriceConverter(6, 18).price_to_x96(price, True)
    
    """

    X96FACTOR = 1 << 96
    
    def __init__(self, decimal0: int, decimal1: int):
        self.decimal0 = decimal0
        self.decimal1 = decimal1
        self.factor = 10**(self.decimal1-self.decimal0)
    
    def x96_to_price(self, x96, reverse: bool=False):
        if not reverse:
            return  (int(x96)/(self.X96FACTOR))**2 / self.factor
        else:
            return self.factor / (int(x96)/(self.X96FACTOR))**2 
    
    def price_to_x96(self, price: float, reverse: bool=False):
        return int(math.sqrt(self.price_to_dex(price, reverse)) * self.X96FACTOR)

    def x96_to_price_reverse(self, x96):
        return self.factor / (int(x96)/(self.X96FACTOR))**2 
    
    def price_to_dex(self, price: float, reverse: bool=False):
        if not reverse:
            return price * self.factor
        else:
            return self.factor / price
        
    def price_to_tick(self, price: float, reverse: bool=False):
        return int(math.log(self.price_to_dex(price, reverse), 1.0001))
    
    def tick_to_price(self, tick: int, reverse: bool=False):
        if not reverse:
            return  1.0001**tick / self.factor
        else:
            return self.factor / 1.0001**tick