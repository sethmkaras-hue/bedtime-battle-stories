"""Stateless, reproducible story-game progression. Ratings are game design, not science."""
import hashlib
import random

UPSET_CHANCE = {'realistic': .10, 'balanced': .30, 'anything': .50}
# Deliberately fictional game ratings. They are not biological measurements.
POWERFUL = {'Tyrannosaurus','Triceratops','Ankylosaurus','Brachiosaurus','Diplodocus',
            'Spinosaurus','Giganotosaurus','Mosasaurus','Tylosaurus','Kronosaurus',
            'Great white shark','Tiger shark','Bull shark','Great hammerhead'}
SMALL = {'Compsognathus','Microraptor','Psittacosaurus','Protoceratops',
         'Small-spotted catshark','Horn shark','Epaulette shark','Brownbanded bamboo shark'}


def rating(creature):
    if 'gameplay_rating' in creature:
        return creature['gameplay_rating']
    return 5 if creature['name'] in POWERFUL else 2 if creature['name'] in SMALL else 3


def winner_for(left, right, seed, match_id, realism):
    digest = hashlib.sha256(f'{seed}:{match_id}'.encode()).digest()
    rng = random.Random(int.from_bytes(digest, 'big'))
    if rating(left) == rating(right):
        return rng.choice([left, right])
    favorite, outsider = sorted([left, right], key=rating, reverse=True)
    return outsider if rng.random() < UPSET_CHANCE[realism] else favorite


def chapter(left, right, winner, duration, arena, match_id):
    a, b = left['name'], right['name']
    place = 'a quiet moonlit clearing' if arena == 'land' else 'a wide stretch of moonlit sea'
    intro = f'Tonight, in our make-believe adventure, {a} and {b} meet beside {place}. The stars shine above them. This is a friendly contest of courage and clever choices. Both creatures will be safe when the chapter ends.'
    scenes = [
        f'{a} waits and watches. {b} takes a little time too. Neither creature needs to hurry. They are looking for a good moment to begin. Around them, the world seems to hold its breath. A cloud drifts slowly past the moon.',
        f'The first challenge is a game of space. {a} moves one way, and {b} answers with a careful turn. There is room for both of them. The contest is close. One patient choice can matter more than a great big show of strength.',
        'For a moment everything becomes still. Our two adventurers pause, gather their courage, and try again. There are no bad creatures here. Each has a different way of meeting a challenge. Even a surprising idea can work in a make-believe story.',
        f'{b} makes a bold move. {a} finds a way to stay in the contest. The moon shines on their adventure like a little night-light. Far away, the rest of the world is settling down. Here, one more puzzle is waiting to be solved.',
        'The challenge asks for patience. A quick start is useful, but so is knowing when to wait. Both adventurers take their time. Each finds a small moment to try something different. The contest feels like a question that has more than one clever answer.',
        f'{a} changes the plan. {b} notices and changes too. Back and forth the friendly challenge goes. Sometimes one seems ahead, and sometimes the other. We can cheer for both, because being brave does not always mean being the one who wins.',
        'A gentle hush settles over the scene. Our adventurers look for a clear path through the final challenge. There is no need to rush toward the ending. Every quiet moment is another chance to notice something new and make a thoughtful choice.',
        'Now the last part of the contest begins. Both creatures have tried their best. They have been patient, bold, and curious. Whatever happens next, there will be time to rest afterward. The stars will still be shining, and the world will still be wide.',
    ]
    target = {'short': 130, 'normal': 260, 'long': 390}[duration]
    verified_context = []
    for creature in [left,right]:
        profile = creature.get('profile') or {}
        if profile.get('verification_status') == 'verified':
            verified_context.append({'creature_id':creature['id'], 'facts':profile['fun_facts'],
                                     'offense':profile['offensive_adaptations'], 'defense':profile['defensive_adaptations']})
    paragraphs = [intro]
    for context in verified_context:
        if context['facts']:
            paragraphs.append('A little discovery before our pretend contest: ' + context['facts'][0])
    for scene in scenes:
        if len(' '.join(paragraphs).split()) >= target:
            break
        paragraphs.append(scene)
    ending = f"And the winner of this make-believe match is {winner['name']}! Both adventurers are safe. They settle down to rest beneath the quiet sky."
    # Keep the ending separate so the visible player never spoils it early.
    return {'match_id': match_id, 'title': f'{a} and {b}', 'paragraphs': paragraphs,
            'ending': ending, 'participants': [left, right], 'generated_by': 'local_template',
            'verified_creature_context': verified_context,
            'note': 'A fictional story game. Ratings and upset chances are game rules, not scientific predictions.'}


def progress(tournament, seed, completed, realism, duration):
    finished = 0
    next_chapter = None
    for round_index, round_ in enumerate(tournament['rounds']):
        for match in round_['matches']:
            if match['sources']:
                previous = {m['id']: m for m in tournament['rounds'][round_index-1]['matches']}
                for side, source in zip(['left', 'right'], match['sources']):
                    match[side] = previous[source]['winner']
            if match['left'] and match['right']:
                winner = winner_for(match['left'], match['right'], seed, match['id'], realism)
                if finished < completed:
                    match.update(winner=winner, status='complete')
                elif next_chapter is None:
                    next_chapter = chapter(match['left'], match['right'], winner, duration, tournament['arena'], match['id'])
            finished += 1
    tournament.update(seed=seed, completed=completed, chapter=next_chapter,
                      champion=tournament['rounds'][-1]['matches'][0]['winner'],
                      placeholder=False, story_mode='local_template')
    return tournament
