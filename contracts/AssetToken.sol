// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract AssetToken is ERC20 {
    constructor() ERC20("Asset Token", "AST") {
        _mint(msg.sender, 1_000 * 10 ** decimals());
    }
}
