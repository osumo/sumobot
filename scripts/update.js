
"use strict";

let child_process = require("child_process");

module.exports = (robot) => {
  let currentRevision = child_process.spawnSync(
    "git",
    [ "rev-parse", "--no-flags", "HEAD"],
    { "stdio": ["ignore", "pipe", "ignore"] }
  ).stdout.toString();

  robot.respond(/update/i, (res) => {
    child_process.spawnSync(
      "git", ["fetch", "--all"], { "stdio": "ignore" }
    );
    child_process.spawnSync(
      "git", ["pull"], { "stdio": "ignore" }
    );

    let newRevision = child_process.spawnSync(
      "git",
      [ "rev-parse", "--no-flags", "HEAD"],
      { "stdio": ["ignore", "pipe", "ignore"] }
    ).stdout.toString();

    if(newRevision == currentRevision) {
      res.reply(`already at latest revision: ${currentRevision}`);
    } else {
      res.reply(`upgrading from ${currentRevision} to ${newRevision}`);
      robot.shutdown();

      console.log("   === RESTARTING ===   ");
      setTimeout(() => process.exit(42), 1000);
    }
  });
}

