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

    def set_time_control(self, game):
        pass

    def first_search(self, board, movetime):
        pass

    def search(self, board, wtime, btime, winc, binc):
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
        commands = commands[0] if len(commands) == 1 else commands
        self.go_commands = options.get("go_commands", {})

        self.engine = chess.uci.popen_engine(commands, stderr=subprocess.DEVNULL if silence_stderr else None)
        self.engine.uci()

        if options:
            self.engine.setoption(options)

        self.engine.setoption({
            "UCI_Variant": type(board).uci_variant,
            "UCI_Chess960": board.chess960
        })
        self.engine.position(board)

        info_handler = chess.uci.InfoHandler()
        self.engine.info_handlers.append(info_handler)

    def first_search(self, board, movetime):
        self.engine.position(board)
        best_move, _ = self.engine.go(movetime=movetime)
        return best_move

    def search_with_ponder(self, board, wtime, btime, winc, binc, ponder=False):
        self.engine.position(board)
        best_move, ponder_move = self.engine.go(
            wtime=wtime,
            btime=btime,
            winc=winc,
            binc=binc,
            ponder=ponder
        )
        return (best_move, ponder_move)

    def search(self, board, wtime, btime, winc, binc):
        self.engine.position(board)
        cmds = self.go_commands
        best_move, _ = self.engine.go(
            wtime=wtime,
            btime=btime,
            winc=winc,
            binc=binc,
            depth=cmds.get("depth"),
            nodes=cmds.get("nodes"),
            movetime=cmds.get("movetime")
        )
        return best_move

    def stop(self):
        self.engine.stop()

    def print_stats(self):
        print_handler_stats(self.engine.info_handlers[0].info, ["string", "depth", "nps", "nodes", "score"])

    def get_stats(self):
        return get_handler_stats(self.engine.info_handlers[0].info, ["depth", "nps", "nodes", "score"])

    def get_opponent_info(self, game):
        name = game.opponent.name
        if name:
            rating = game.opponent.rating if game.opponent.rating is not None else "none"
            title = game.opponent.title if game.opponent.title else "none"
            player_type = "computer" if title == "BOT" else "human"
            self.engine.setoption({"UCI_Opponent": "{} {} {} {}".format(title, rating, player_type, name)})


class XBoardEngine(EngineWrapper):
    class GameState(Enum):
        FirstMove = auto()
        OtherMove = auto()

    def __init__(self, board, commands, options=None, silence_stderr=False):
        self.engine = chess.engine.SimpleEngine.popen_xboard(commands)
        self.engine.configure(options)

    def first_search(self, board, movetime):
        result = self.engine.play(board,
                                  chess.engine.Limit(time=movetime/1000),
                                  info=chess.engine.INFO_CURRLINE,
                                  game=XBoardEngine.GameState.FirstMove)
        return result.move

    def search(self, board, wtime, btime, winc, binc):
        time_limit = chess.engine.Limit(white_clock=wtime/1000,
                                        black_clock=btime/1000,
                                        white_inc=winc/1000,
                                        black_inc=binc/1000,
                                        remaining_moves=10000)
        result = self.engine.play(board,
                                  time_limit,
                                  info=chess.engine.INFO_CURRLINE,
                                  game=XBoardEngine.GameState.OtherMove)
        return result.move

    def search_with_ponder(self, board, wtime, btime, winc, binc, ponder=False):
        return self.search(board, wtime, btime, winc, binc), None

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
