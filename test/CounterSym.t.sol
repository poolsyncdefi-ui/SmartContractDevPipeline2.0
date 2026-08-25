// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../contracts/Counter.sol";

contract CounterTest is Test {
    Counter public counter;

    function setUp() public {
        counter = new Counter();
    }

    // Test Foundry standard
    function test_Increment() public {
        counter.increment();
        assertEq(counter.count(), 1);
    }

    function test_Decrement() public {
        counter.increment();
        counter.decrement();
        assertEq(counter.count(), 0);
    }

    function test_DecrementRevertsWhenZero() public {
        vm.expectRevert("Counter: count underflow");
        counter.decrement();
    }

    // Test Halmos symbolique (déjà présent)
    function check_increment(uint256 initialCount) public {
        // Ce test est utilisé par Halmos
    }
}