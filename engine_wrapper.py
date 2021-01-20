import os
import chess
import chess.engine
import backoff
import subprocess
from enum import Enum, auto


@backoff.on_exception(backoff.expo, BaseException, max_time=120)
def create_engine(config, board):
    cfg = config["engine"]
    engine_path = os.path.join(cfg["dir"], cfg["name"])
    engine_type = cfg.get("protocol")
    engine_options = cfg.get("engine_options")
    commands = [engine_path]
    if engine_options:
        for k, v in engine_options.items():
            commands.append("--{}={}".format(k, v))

    silence_stderr = cfg.get("silence_stderr", False)

    if engine_type == "xboard":
        return XBoardEngine(board, commands, cfg.get("xboard_options", {}) or {}, silence_stderr)

    return UCIEngine(board, commands, cfg.get("uci_options", {}) or {}, silence_stderr)


def print_handler_stats(info, stats):
    for stat in stats:
        if stat in info:
            print("    {}: {}".format(stat, info[stat]))


def get_handler_stats(info, stats):
    stats_str = []
    for stat in stats:
        if stat in info:
            stats_str.append("{}: {}".format(stat, info[stat]))

    return stats_str


class EngineWrapper:
    def __init__(self, board, commands, options=None, silence_stderr=False):
        pass

    def first_search(self, board, movetime):
        pass

    def search_with_ponder(self, board, wtime, btime, winc, binc, ponder=False):
        pass

    def print_stats(self):
        pass

    def get_opponent_info(self, game):
        pass

    def name(self):
        return self.engine.id["name"]

    def stop(self):
        pass

    def quit(self):
        self.engine.quit()


class UCIEngine(EngineWrapper):
    def __init__(self, board, commands, options, silence_stderr=False):
        self.go_commands = options.get("go_commands", {})
        if self.go_commands:
            del options["go_commands"]
        self.engine = chess.engine.SimpleEngine.popen_uci(commands, stderr=subprocess.DEVNULL if silence_stderr else None)
        for option, value in options.items():
            self.engine.protocol._setoption(option, value)

    def first_search(self, board, movetime):
        result = self.engine.play(board, chess.engine.Limit(time=movetime/1000))
        return result.move

    def search_with_ponder(self, board, wtime, btime, winc, binc, ponder=False):
        cmds = self.go_commands
        time_limit = chess.engine.Limit(white_clock=wtime/1000,
                                        black_clock=btime/1000,
                                        white_inc=winc/1000,
                                        black_inc=binc/1000,
                                        depth=cmds.get("depth"),
                                        nodes=cmds.get("nodes"),
                                        time=cmds.get("movetime"))
        result = self.engine.play(board, time_limit, ponder=ponder)
        return (result.move, result.ponder)

    def stop(self):
        self.engine.protocol.send_line("stop")

    def print_stats(self):
        pass # print_handler_stats(self.engine.info_handlers[0].info, ["string", "depth", "nps", "nodes", "score"])

    def get_stats(self):
        pass # return get_handler_stats(self.engine.info_handlers[0].info, ["depth", "nps", "nodes", "score"])

    def get_opponent_info(self, game):
        name = game.opponent.name
        if name:
            rating = game.opponent.rating if game.opponent.rating is not None else "none"
            title = game.opponent.title if game.opponent.title else "none"
            player_type = "computer" if title == "BOT" else "human"
            try:
                self.engine.protocol._setoption("UCI_Opponent", f"{title} {rating} {player_type} {name}")
            except chess.engine.EngineError:
                pass


class XBoardEngine(EngineWrapper):
    class GameState(Enum):
        FirstMove = auto()
        OtherMove = auto()

    def __init__(self, board, commands, options=None, silence_stderr=False):
        self.engine = chess.engine.SimpleEngine.popen_xboard(commands, stderr=subprocess.DEVNULL if silence_stderr else None)
        self.engine.configure(options)

    def first_search(self, board, movetime):
        result = self.engine.play(board,
                                  chess.engine.Limit(time=movetime//1000),
                                  info=chess.engine.INFO_CURRLINE,
                                  game=XBoardEngine.GameState.FirstMove)
        return result.move

    def search_with_ponder(self, board, wtime, btime, winc, binc, ponder=False):
        time_limit = chess.engine.Limit(white_clock=wtime/1000,
                                        black_clock=btime/1000,
                                        white_inc=winc/1000,
                                        black_inc=binc/1000,
                                        remaining_moves=10000)
        result = self.engine.play(board,
                                  time_limit,
                                  info=chess.engine.INFO_CURRLINE,
                                  game=XBoardEngine.GameState.OtherMove,
                                  ponder=ponder)
        return result.move, None

    def stop(self):
        self.engine.protocol.send_line("?")

    def print_stats(self):
        pass # print_handler_stats(self.engine.post_handlers[0].post, ["depth", "nodes", "score"])

    def get_stats(self):
        pass # return get_handler_stats(self.engine.post_handlers[0].post, ["depth", "nodes", "score"])

    def get_opponent_info(self, game):
        title = game.opponent.title + " " if game.opponent.title else ""
        if game.opponent.name:
            self.engine.protocol.send_line(f"name {title}{game.opponent.name}")
        if game.me.rating is not None and game.opponent.rating is not None:
            self.engine.protocol.send_line(f"rating {game.me.rating} {game.opponent.rating}")
        if game.opponent.title == "BOT":
            self.engine.protocol.send_line("computer")
