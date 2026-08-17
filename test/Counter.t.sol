// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "contracts/Counter.sol";

contract CounterTest {
    // Test de propriété symbolique : après un incrément, count doit augmenter de 1
    function check_increment(uint256 initialCount) public {
        Counter counter = new Counter();
        
        // Pour simuler un état arbitraire si nécessaire, ou tester directement
        counter.increment();
        assert(counter.count() == 1);
    }
}