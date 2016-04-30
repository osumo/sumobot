/*
 * Description:
 *   updates hubot to the latest version from origin/master
 *
 * Dependencies:
 *   "git (command line)": ""
 *
 * Configuration:
 *
 * Commands:
 *   hubot update - updates this bot's code to the latest version
 *
 * Author:
 *   opadron
 */

"use strict";

let child_process = require("child_process");

module.exports = (robot) => {
  let currentBotRevision = robot.brain.get("currentBotRevision");
  if(!currentBotRevision) {
    currentBotRevision = child_process.spawnSync(
      "git",
      [ "rev-parse", "--no-flags", "HEAD"],
      { "stdio": ["ignore", "pipe", "ignore"] }
    ).stdout.toString();

    robot.brain.set("currentBotRevision", currentBotRevision);
  }

  robot.respond(/update/i, (res) => {
    child_process.spawnSync(
      "git", ["fetch", "--all"], { "stdio": "ignore" }
    );
    child_process.spawnSync(
      "git", ["checkout", "master"], { "stdio": "ignore" }
    );
    child_process.spawnSync(
      "git", ["pull"], { "stdio": "ignore" }
    );

    let newBotRevision = child_process.spawnSync(
      "git",
      ["rev-parse", "--no-flags", "HEAD"],
      { "stdio": ["ignore", "pipe", "ignore"] }
    ).stdout.toString();

    if(newBotRevision == currentBotRevision) {
      res.reply(`already at latest revision: ${currentBotRevision}`);
    } else {
      res.reply(`upgrading from ${currentBotRevision} to ${newBotRevision}`);
      child_process.spawnSync(
        "git",
        ["submodule", "update", "gobig"],
        { "stdio": "ignore" }
      );

      robot.brain.set("currentBotRevision", newBotRevision);
      robot.shutdown();

      console.log("   === RESTARTING ===   ");
      setTimeout(() => process.exit(42), 1000);
    }
  });
}

