"""Coin Pusher Game with Pymunk & Pygame

真上から見たコインプッシャー。
  - 往復するプッシャー台(KINEMATIC)がコインを手前へ押し出す
  - 手前中央の「獲得口」に落ちると +1、左右の「回収口」に落ちると消えるだけ
  - 所持メダルが0だと投入できない(獲得したメダルは所持枚数にも加算)

操作: マウス / ←→ で位置、クリック / SPACE で投入、R でリセット、ESC で終了
"""
import math
import random
import sys

import pygame
import pymunk

# ---------------------------------------------------------------- 定数
WIDTH, HEIGHT = 560, 680
FPS = 60
SUBSTEPS = 3  # 1フレームあたりの物理ステップ数(すり抜け防止)

# フィールド (画面座標: 上が奥、下が手前)
FIELD_L, FIELD_R = 100, 460
BACK_Y = 100          # 奥の壁
EDGE_Y = 540          # 手前の縁(ここを越えたら落下)
GOAL_L, GOAL_R = 145, 415  # 獲得口の範囲(それ以外の縁は回収口)
WALL_R = 4            # 壁の太さ(半径)

# プッシャー
PUSHER_W = FIELD_R - FIELD_L - 2 * WALL_R - 2
PUSHER_H = 44
PUSHER_STROKE = 90    # 往復の幅
PUSHER_PERIOD = 3.0   # 1往復にかかる秒数
PUSHER_MIN_Y = BACK_Y + WALL_R + 4 + PUSHER_H / 2  # 一番奥に引いた時の中心Y

# コイン
COIN_R = 14
COIN_MASS = 1.0
START_MEDALS = 80
DROP_COOLDOWN = 0.12  # 連続投入の最短間隔(秒)
PENDING_TIME = 0.6    # 投入位置が塞がっている時に待つ秒数
SHOOTER_Y = 64
SHOOTER_SPEED = 320
SPAWN_GAP = COIN_R + 4  # 投入位置: プッシャー前面からコイン中心までの距離

# 色
BG = (18, 22, 32)
TABLE = (32, 50, 68)
WALL_COLOR = (150, 160, 175)
PUSHER_FILL = (86, 108, 150)
PUSHER_EDGE = (150, 175, 220)
GOLD = (245, 200, 60)
GOLD_EDGE = (170, 125, 20)
GOAL_COLOR = (40, 120, 70)
OUT_COLOR = (120, 45, 50)
TEXT = (235, 238, 245)
SUB_TEXT = (150, 160, 180)

FONT_CANDIDATES = [
    "notosanscjkjp", "notosansjp", "notosanscjk", "ipaexgothic", "ipagothic",
    "takaogothic", "vlgothic", "meiryo", "yugothic", "msgothic",
    "hiraginosans", "hiraginokakugothicpro", "applesdgothicneo",
]
LABELS_JP = {
    "medals": "所持メダル", "score": "獲得", "field": "場のコイン",
    "goal": "獲得口", "out": "回収口",
    "help": "マウス/←→:位置  クリック/SPACE:投入  R:リセット  ESC:終了",
    "empty": "メダルがありません  R でリスタート",
}
LABELS_EN = {
    "medals": "Medals", "score": "Score", "field": "On field",
    "goal": "GOAL", "out": "OUT",
    "help": "Mouse/Arrows: aim  Click/SPACE: drop  R: reset  ESC: quit",
    "empty": "Out of medals  -  press R to restart",
}


def pusher_y(t):
    """時刻 t でのプッシャー中心Y (なめらかな往復)。"""
    phase = (1 - math.cos(2 * math.pi * t / PUSHER_PERIOD)) / 2
    return PUSHER_MIN_Y + PUSHER_STROKE * phase


# ---------------------------------------------------------------- ゲーム本体
class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        self.space = pymunk.Space()
        self.space.gravity = (0, 0)   # 真上から見た図なので重力なし
        self.space.damping = 0.08     # 台の上の摩擦の代わりに速度を減衰させる
        self.space.iterations = 20    # コインが密集しても安定するように

        self.coins = []
        self.medals = START_MEDALS
        self.score = 0
        self.time = 0.0
        self.cooldown = 0.0
        self.pending = 0.0
        self.shooter_x = (FIELD_L + FIELD_R) / 2
        self.popups = []              # [x, y, 残り秒, 文字]

        self._build_field()
        self._build_pusher()
        self._place_initial_coins()

    # --- 構築 -----------------------------------------------------------
    def _build_field(self):
        """動かない外壁(STATIC)。左右と奥を囲み、手前は開けておく。"""
        static = self.space.static_body
        walls = [
            ((FIELD_L, BACK_Y), (FIELD_L, EDGE_Y)),
            ((FIELD_R, BACK_Y), (FIELD_R, EDGE_Y)),
            ((FIELD_L, BACK_Y), (FIELD_R, BACK_Y)),
        ]
        for a, b in walls:
            seg = pymunk.Segment(static, a, b, WALL_R)
            seg.friction = 0.3
            seg.elasticity = 0.2
            self.space.add(seg)

    def _build_pusher(self):
        """往復するプッシャー(KINEMATIC)。摩擦を高くして押し出しやすくする。"""
        self.pusher = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        self.pusher.position = ((FIELD_L + FIELD_R) / 2, pusher_y(0))
        self.pusher_shape = pymunk.Poly.create_box(self.pusher, (PUSHER_W, PUSHER_H))
        self.pusher_shape.friction = 1.5
        self.pusher_shape.elasticity = 0.1
        self.space.add(self.pusher, self.pusher_shape)

    def _place_initial_coins(self):
        """最初から台の上にコインを並べておく(千鳥配置)。"""
        step = COIN_R * 2 + 3
        cx = (FIELD_L + FIELD_R) / 2
        for row in range(9):
            n = 9 - row % 2
            y = 282 + row * step * 0.9
            for i in range(n):
                x = cx + (i - (n - 1) / 2) * step
                self._add_coin(x, y)

    def _add_coin(self, x, y):
        moment = pymunk.moment_for_circle(COIN_MASS, 0, COIN_R)
        body = pymunk.Body(COIN_MASS, moment)
        body.position = (x, y)
        body.angle = random.uniform(0, math.tau)
        shape = pymunk.Circle(body, COIN_R)
        shape.friction = 0.6
        shape.elasticity = 0.25
        self.space.add(body, shape)
        self.coins.append(shape)

    def _remove_coin(self, shape):
        self.space.remove(shape, shape.body)
        self.coins.remove(shape)

    # --- 入力 -----------------------------------------------------------
    def request_drop(self):
        """投入要求。位置が塞がっていても PENDING_TIME の間は待ってくれる。"""
        self.pending = PENDING_TIME

    def spawn_y(self):
        """投入位置のY。常にプッシャーの手前(前面のすぐ前)に落とす。"""
        return self.pusher.position.y + PUSHER_H / 2 + SPAWN_GAP

    def _try_drop(self):
        if self.medals <= 0 or self.cooldown > 0:
            return False
        lo = FIELD_L + WALL_R + COIN_R + 1
        hi = FIELD_R - WALL_R - COIN_R - 1
        x = min(max(self.shooter_x, lo), hi)
        # 台や他のコインと重なる位置には投入しない(重なると弾け飛ぶため)
        y = self.spawn_y()
        info = self.space.point_query_nearest((x, y), COIN_R * 2, pymunk.ShapeFilter())
        if info is not None and info.distance < COIN_R:
            return False
        self._add_coin(x, y)
        self.medals -= 1
        self.cooldown = DROP_COOLDOWN
        return True

    # --- 更新 -----------------------------------------------------------
    def move_shooter(self, dx):
        self.shooter_x += dx

    def update(self, dt):
        self.shooter_x = min(max(self.shooter_x, FIELD_L), FIELD_R)
        self.cooldown = max(0.0, self.cooldown - dt)

        if self.pending > 0:
            self.pending -= dt
            if self._try_drop():
                self.pending = 0

        sub_dt = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            self.time += sub_dt
            # 次の位置に丁寧に到達する速度を与える(位置のズレが溜まらない)
            target = pusher_y(self.time)
            self.pusher.velocity = (0, (target - self.pusher.position.y) / sub_dt)
            self.space.step(sub_dt)

        self._judge_coins()

        for p in self.popups:
            p[1] -= 30 * dt
            p[2] -= dt
        self.popups = [p for p in self.popups if p[2] > 0]

    def _judge_coins(self):
        """手前の縁を越えたコインを判定して消す。"""
        for coin in list(self.coins):
            x, y = coin.body.position
            if y > EDGE_Y:
                if GOAL_L <= x <= GOAL_R:      # 獲得口
                    self.score += 1
                    self.medals += 1
                    self.popups.append([x, EDGE_Y + 10, 0.8, "+1"])
                self._remove_coin(coin)        # 回収口は加算なしで消すだけ
            elif not (FIELD_L - 40 < x < FIELD_R + 40 and y > BACK_Y - 40):
                self._remove_coin(coin)        # 万一フィールド外に出た場合の保険


# ---------------------------------------------------------------- 描画
class Renderer:
    def __init__(self):
        self.font_big, ok = self._load_font(26)
        self.font, _ = self._load_font(18)
        self.font_small, _ = self._load_font(14)
        self.labels = LABELS_JP if ok else LABELS_EN

    @staticmethod
    def _load_font(size):
        for name in FONT_CANDIDATES:
            path = pygame.font.match_font(name)
            if path:
                return pygame.font.Font(path, size), True
        return pygame.font.Font(None, size + 4), False  # 日本語フォントが無い場合

    def _text(self, screen, font, text, pos, color=TEXT, center=False):
        img = font.render(text, True, color)
        rect = img.get_rect()
        if center:
            rect.center = pos
        else:
            rect.topleft = pos
        screen.blit(img, rect)

    def draw(self, screen, game):
        L = self.labels
        screen.fill(BG)

        # 台
        pygame.draw.rect(screen, TABLE, (FIELD_L, BACK_Y, FIELD_R - FIELD_L, EDGE_Y - BACK_Y))

        # 手前の判定ゾーン
        tray_h = 60
        zones = [
            (FIELD_L, GOAL_L, OUT_COLOR, L["out"]),
            (GOAL_L, GOAL_R, GOAL_COLOR, L["goal"]),
            (GOAL_R, FIELD_R, OUT_COLOR, L["out"]),
        ]
        for x0, x1, color, name in zones:
            pygame.draw.rect(screen, color, (x0, EDGE_Y, x1 - x0, tray_h))
            font = self.font if x1 - x0 > 100 else self.font_small
            self._text(screen, font, name, ((x0 + x1) // 2, EDGE_Y + tray_h // 2), center=True)

        # 壁
        for a, b in [((FIELD_L, BACK_Y), (FIELD_L, EDGE_Y)),
                     ((FIELD_R, BACK_Y), (FIELD_R, EDGE_Y)),
                     ((FIELD_L, BACK_Y), (FIELD_R, BACK_Y))]:
            pygame.draw.line(screen, WALL_COLOR, a, b, WALL_R * 2)

        # プッシャー
        body, shape = game.pusher, game.pusher_shape
        pts = [body.local_to_world(v) for v in shape.get_vertices()]
        pygame.draw.polygon(screen, PUSHER_FILL, pts)
        pygame.draw.polygon(screen, PUSHER_EDGE, pts, 3)
        top = min(p.y for p in pts)
        for x in range(FIELD_L + 20, FIELD_R - 10, 24):
            pygame.draw.line(screen, PUSHER_EDGE, (x, top + 8), (x + 10, top + PUSHER_H - 8), 2)

        # コイン
        for coin in game.coins:
            self._draw_coin(screen, coin.body.position, coin.body.angle)

        # シューター(投入位置)
        lo = FIELD_L + WALL_R + COIN_R + 1
        hi = FIELD_R - WALL_R - COIN_R - 1
        sx = min(max(game.shooter_x, lo), hi)
        spawn_y = game.spawn_y()
        pygame.draw.line(screen, SUB_TEXT, (sx, SHOOTER_Y + 14), (sx, spawn_y - COIN_R), 1)
        pygame.draw.polygon(screen, GOLD, [(sx - 14, SHOOTER_Y - 12), (sx + 14, SHOOTER_Y - 12), (sx, SHOOTER_Y + 14)])
        pygame.draw.circle(screen, SUB_TEXT, (int(sx), int(spawn_y)), COIN_R, 1)

        # +1 ポップアップ
        for x, y, _, msg in game.popups:
            self._text(screen, self.font_big, msg, (x, y), color=(140, 255, 170), center=True)

        # UI
        self._text(screen, self.font_small, L["medals"], (20, 12), SUB_TEXT)
        self._text(screen, self.font_big, str(game.medals), (20, 30))
        self._text(screen, self.font_small, L["score"], (WIDTH // 2 - 30, 12), SUB_TEXT)
        self._text(screen, self.font_big, str(game.score), (WIDTH // 2 - 30, 30), (140, 255, 170))
        self._text(screen, self.font_small, L["field"], (WIDTH - 110, 12), SUB_TEXT)
        self._text(screen, self.font_big, str(len(game.coins)), (WIDTH - 110, 30))

        if game.medals <= 0:
            self._text(screen, self.font_big, L["empty"], (WIDTH // 2, 110 + 40), (255, 130, 130), center=True)
        self._text(screen, self.font_small, L["help"], (WIDTH // 2, HEIGHT - 20), SUB_TEXT, center=True)

    @staticmethod
    def _draw_coin(screen, pos, angle):
        c = (int(pos.x), int(pos.y))
        pygame.draw.circle(screen, GOLD_EDGE, c, COIN_R)
        pygame.draw.circle(screen, GOLD, c, COIN_R - 2)
        pygame.draw.circle(screen, GOLD_EDGE, c, COIN_R - 6, 1)
        # 回転が分かるように印を付ける
        tip = (c[0] + math.cos(angle) * (COIN_R - 4), c[1] + math.sin(angle) * (COIN_R - 4))
        pygame.draw.line(screen, GOLD_EDGE, c, tip, 2)


# ---------------------------------------------------------------- メイン
def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Coin Pusher - Pymunk & Pygame")
    clock = pygame.time.Clock()
    game = Game()
    renderer = Renderer()
    dt = 1.0 / FPS

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    game.reset()
            elif event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
                game.shooter_x = event.pos[0]

        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]:
            game.move_shooter(-SHOOTER_SPEED * dt)
        if keys[pygame.K_RIGHT]:
            game.move_shooter(SHOOTER_SPEED * dt)
        if pygame.mouse.get_pressed()[0] or keys[pygame.K_SPACE]:
            game.request_drop()  # 押しっぱなしで連続投入

        game.update(dt)
        renderer.draw(screen, game)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
