/*
 * Description:
 *   handles the deployment of osumo.org
 *
 * Dependencies:
 *   "python (command line)": ""
 *
 * Commands:
 *   hubot stage [revision] - stages the specified revision
 *   hubot deploy - deploys the staged revision
 *
 * Author:
 *   opadron
 */

"use strict";

let child_process = require("child_process");

const checkDevOps = (robot, res, op) => {
  let devopsInProgress = robot.brain.get("devopsInProgress");
  let result = (devopsInProgress === "staging" ||
                devopsInProgress === "deployment");

  if(result) {
    res.reply(
      `cannot ${op}: ${devopsInProgress} operation currently in progress`);
  }

  return result;
};

module.exports = (robot) => {
  robot.respond(/stage(.*)/i, (res) => {
    if(!checkDevOps(robot, res, "stage")) {
      robot.brain.set("devopsInProgress", "staging");
      let commandArgs = ["main.py", "stage"];
      let revision = res.match[1].trim();
      if(revision) {
        commandArgs.push("--revision");
        commandArgs.push(revision);
      }

      let proc = child_process.spawn("python", commandArgs);

      proc.stdout.on("data", (data) => {
        let match = data.toString().match(/^BOT: (.*)/);
        if(match) {
          res.reply(match[1]);
        }
      });

      proc.stderr.on("data", (data) => {
        res.reply(`ERR: ${data}`);
      });

      proc.on("close", (code) => {
        if(code !== 0) {
          res.reply(`process exited with code: ${code}`);
        }
        robot.brain.set("devopsInProgress", "none");
      });
    }
  });
}

