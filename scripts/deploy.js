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
        data = data.toString().split("\n");
        let i;
        let match;
        for(i=0; i<data.length - 1; ++i) {
          match = data[i].match(/^BOT: (.*)/);
          if(match) {
            res.reply(match[1]);
          }
          console.log(data[i]);
        }

        let last = data[data.length - 1];
        if(last !== "") {
          match = last.match(/^BOT: (.*)/);
          if(match) {
            res.reply(match[1]);
          }
          console.log(last);
        }
      });

      proc.stderr.on("data", (data) => {
        data = data.toString().split("\n");
        let i;
        for(i=0; i<data.length - 1; ++i) {
          res.reply(`ERR: ${data[i]}`);
          console.log(data[i]);
        }

        let last = data[data.length - 1];
        if(last !== "") {
          res.reply(`ERR: ${last}`);
          console.log(last);
        }
      });

      proc.on("close", (code) => {
        if(code !== 0) {
          let msg = `process exited with code: ${code}`;
          console.log(msg);
          res.reply(msg);
        }
        robot.brain.set("devopsInProgress", "none");
      });
    }
  });
}

