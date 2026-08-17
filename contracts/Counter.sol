// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract Counter {
    uint256 public count;

    event Increment(uint256 newCount);

    function increment() public {
        count += 1;
        emit Increment(count);
    }

    function decrement() public {
        require(count > 0, "Counter: count underflow");
        count -= 1;
    }
}