"""Colour science for the statistics charts.

Give it a count, get back that many hex colours, each as far from its
neighbours as the RGB cube allows. No query touches this module - the
question of which corporation gets which slot lives in eos_tax.db.statistics,
next to the data it depends on.
"""

from functools import lru_cache
from math import sqrt


# How far a colour may stray towards black or white before it stops reading on
# one of the two surfaces. The cube reaches into both corners.
CHART_MIN_LIGHTNESS = 0.22


CHART_MAX_LIGHTNESS = 0.78


# How close red, green and blue may sit before the colour is a grey. The cube
# has a full diagonal of them and they read as each other on a chart.
CHART_MIN_SPREAD = 40


def _lightness(rgb):
    return (max(rgb) + min(rgb)) / 510


def _hue(rgb):
    red, green, blue = (channel / 255 for channel in rgb)
    high, low = max(red, green, blue), min(red, green, blue)
    span = high - low

    if not span:
        return 0.0

    if high == red:
        return ((green - blue) / span % 6) * 60
    if high == green:
        return ((blue - red) / span + 2) * 60

    return ((red - green) / span + 4) * 60


def _saturation(rgb):
    high, low = max(rgb) / 255, min(rgb) / 255
    span = high - low

    if not span:
        return 0.0

    return span / (2 - high - low) if (high + low) > 1 else span / (high + low)


def _oklab(rgb):
    """Perceptual coordinates, so a distance means what the eye sees.

    Plain RGB distance says #008000 and #00a000 are as far apart as #000080 and
    #0000a0, which is nonsense - the eye separates greens far better than blues.
    """
    def linear(channel):
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)

    long = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)

    return (
        0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short,
    )


def _distance(first, second):
    return sqrt(sum((a - b) ** 2 for a, b in zip(_oklab(first), _oklab(second)))) * 100


def _cube_colours(count):
    """`count` colours, each the midpoint of one subcube of the RGB cube.

    Cutting every axis into the same number of segments gives cuts**3 cubes, so
    the number of colours grows cubically - three cuts already cover 27
    corporations, four cover 64.
    """
    if count < 1:
        return []

    cuts = 1
    while cuts ** 3 < count:
        cuts += 1

    usable = []
    while True:
        piece = 255 // cuts
        candidates = []

        for index in range(cuts ** 3):
            blue = (index % cuts) * piece + piece // 2
            green = (index // cuts % cuts) * piece + piece // 2
            red = (index // (cuts * cuts) % cuts) * piece + piece // 2
            rgb = (red, green, blue)

            if max(rgb) - min(rgb) < CHART_MIN_SPREAD:
                continue  # the grey diagonal
            if not CHART_MIN_LIGHTNESS <= _lightness(rgb) <= CHART_MAX_LIGHTNESS:
                continue  # too near black or white to read on one of the themes

            candidates.append(rgb)

        if len(candidates) >= count:
            usable = candidates
            break

        cuts += 1  # dropping greys and extremes cost us the headroom

    # Farthest first: start from the most vivid mid-lightness cube, then keep
    # taking whichever colour sits furthest from everything already taken. The
    # answer sorts by hue instead, which is right for rendering the palette as
    # a gradient strip and wrong here - it puts near neighbours on consecutive
    # slots, which is exactly the pair a reader has to tell apart.
    chosen = [
        max(usable, key=lambda rgb: _saturation(rgb) * (1 - abs(_lightness(rgb) - 0.5)))
    ]
    remaining = [rgb for rgb in usable if rgb != chosen[0]]

    while len(chosen) < count:
        pick = max(
            remaining,
            key=lambda rgb: min(_distance(rgb, taken) for taken in chosen),
        )
        chosen.append(pick)
        remaining.remove(pick)

    return chosen


@lru_cache(maxsize=8)
def _chart_palette(count):
    """`count` hex colours, no two of them alike.

    Cached: the answer is the same for a given count, and picking farthest
    first costs count squared distance comparisons.
    """
    return tuple(
        f"#{red:02x}{green:02x}{blue:02x}" for red, green, blue in _cube_colours(count)
    )
