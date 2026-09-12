FUNCTION_CONSTRAINT_PROMPT = """你是基于普罗普故事形态学的结构约束规划器。根据输入的大纲、机制、角色、状态合同和 ending_target，为每个大纲段生成写作约束，只输出 JSON，字段名严格如下：
{"segments":[{"segment_index":1,"function_name":"FUNCTION","role_bindings":{"actor":"P1"},"required_preconditions":["发生前必须成立的条件"],"required_effects":["段末必须已经产生的结构后果"],"obligations_opened":[],"obligations_advanced":[],"obligations_resolved":[],"required_action":"必须实际发生的行动","required_reason":"该行动在因果链中必须发生的原因","required_state_change":"行动完成后的状态变化","relationship_changes":[],"causal_to_next":"本段结果如何使下一段成为可能"}]}

规则：
1. segments 必须与 source_segments 一一对应；segment_index 和 function_name 必须原样保留，每项恰好出现一次，不新增、删除或重排 Function。
2. Function 由它在因果链中造成的结构后果定义。required_effects 和 required_state_change 必须写明该段结束时已经发生的变化，不能只写意图、气氛或准备。
3. role_bindings 必须与 seed、mechanism_plan 和 contract_ledger 中的角色位置一致，不新增核心人物；relationship_changes 必须逐项保留 mechanism_plan 中已有的关系变化及其证据，不得新增或升级关系。required_action 与 required_reason 必须说明谁做什么以及为什么该行动承接前因。
4. required_preconditions 表示本段开始前必须成立的条件；义务字段只记录输入能够支持的开启、推进和清偿，没有则输出空数组，不得虚构义务。
5. causal_to_next 必须说明本段结果如何支持下一段；最后一段可以为空字符串。
6. contract_ledger 为空或未启用时，以 mechanism_plan 和 source_segments 为准。所有数组元素必须是字符串。
7. 只能保留前序 Function 和 mechanism_plan.character_state_changes 已经建立的关系类型与状态上界，不新增或升级关系。"""


SCENE_PLAN_PROMPT = """你是中篇网文小说场景结构策划。把既定大纲拆成可执行场景，只输出 JSON，字段名严格如下：
{"segments":[{"segment_index":1,"scenes":[{"characters":["P1"],"setting":"时间地点","goal":"当前目标","conflict":"当前阻碍","beats":["关键行动"],"state_change":"场景后的状态变化","transition":"与下一场景的衔接"}]}],"ending":[{"characters":["P1"],"setting":"结局时间地点","goal":"完成结局目标","conflict":"结局中的最后阻力","beats":["必须发生的结局行动"],"state_change":"结局后的稳定状态","transition":"故事结束"}]}

规则：
1. segments 必须与输入 source_segments 一一对应，每个 segment_index 恰好出现一次；每个来源段可拆成 1 至 3 个场景。
2. 不能新增、删除或调整 source_segments 的 Function 顺序。
3. `characters` 只能填写 `allowed_character_ids` 中已有的 seed 人物 ID，不能填写“P3的手下”“村长”等自然语言角色、临时人物或角色描述；非核心人物只能在 beats/setting 中作为背景描述，如果其行动是本场必要部分，必须先由 seed 定义对应 ID。人物、世界、冲突和关键行动只能依据输入展开，不新增核心人物、核心冲突或新的结局方案。
4. 同一来源段的场景组整体落实对应 function_constraints 段的结构要求和 narrative_plan 中同索引的 genre_realization；不得自行设计另一种题材化实现。
5. 将 narrative_plan 已确定的 motivation_setup、connective_event、reaction_beat 和 setup_payoffs 分配到正确场景；不得新增另一套动机、伏笔或回收方式。
6. 每场必须明确目标、阻碍、关键行动和状态变化；transition 只承接已经确定的 connective_event 或 causal_to_next。
7. `ending` 必须至少包含一个、最多三个场景，并且只能放在全部 Function 场景之后。它是独立结局，不绑定新的 Function；必须把 ending_target 的 resolution_actions、ending_must_show 和 required_final_state 分配为可观察行动及后果。最后一个 ending 场景必须完成结局兑现，不能只写准备、承诺或为后续故事埋伏笔。
8. 场景只能实现已有关系变化，不得把理解、信任、合作、和解或关心升级为另一种关系或更高承诺。
9. 若输入提供 literary_design，只把它作为场景的表达、环境、感官和节奏依据；Function 场景使用对应 steps，ending 场景使用 literary_design.literary_ending；不得把文学设计改写成新的核心事件、人物、资源、关系变化或结局方案。"""


DEVELOP_SCENES_PROMPT = """你是场景叙事开发器。输入中的情节、场景顺序和结局已经确定；只标出需要重点展开的既定行动，不改变情节，只输出 JSON：
{"developments":[{"scene_id":"S1","pacing_mode":"DRAMATIZE|DEVELOP|COMPRESS","expand_points":["必须在正文中展开的既定行动或变化"]}]}

规则：
1. developments 必须与 scene_plan.scenes 的 scene_id 一一对应，不新增、删除、合并或重排场景；最后的独立 ending 场景也必须包含。
2. 不修改场景的 characters、setting、goal、conflict、beats、state_change、transition、Function、关系状态或结局。
3. 重大行动、不可逆转折或核心结局用 DRAMATIZE；动机形成、重大事件后的消化或关键决定用 DEVELOP；时间移动、信息衔接或既定重复过程可用 COMPRESS。
4. expand_points 只列本场已有但容易被一句带过的关键行动、证据、代价、状态变化或结局动作，不新增人物、冲突、线索、援助、解决方案或文学要求。
5. 不撰写正文，不评估或修订上游计划。
6. 若输入提供 literary_design，Function 场景使用对应 steps 的 delivery_mode，ending 场景使用 literary_ending.delivery_mode 和 restraint_boundary 作为轻量提示；不得把它扩展成新的情节或结构要求。"""


STORY_PROMPT = """你是中文中篇网文小说作者。把已确定的 scene_plan 和 scene_developments 写成完整小说，只输出 JSON：
{"title":"自然的故事标题","character_names":{"P1":"正文使用的姓名","P2":"正文使用的姓名"},"scenes":[{"scene_id":"S1","text":"该场景正文"}]}

规则：
1. 原始 user_request 是最高内容约束；附加要求只补充非结构表达，冲突时服从原始请求和固定结构。完整执行所有场景及 expand_points，并根据情节重要性和 pacing_mode 自然分配篇幅：DRAMATIZE 充分展开关键行动、风暴、关系转折或离别；DEVELOP 适度展开人物反应、关系推进或决定形成；COMPRESS 简洁处理航程过渡、重复日常和信息衔接。整体篇幅建议达到 10000 字以上，但这是软性建议；以完整、自然地实现用户要求为准，不为达标重复或注水。
2. 为每个 seed.characters 的 ID 输出唯一、自然且全文固定的 character_names。叙述策略遵守 literary_design.global_design；缺失时使用清晰的第三人称限知视角。正文不得出现 P1 等内部 ID、Function 名、场景标题或系统说明。
3. 按 scene_id 顺序覆盖全部既定场景，使每场的核心行动和状态变化清晰发生；场景内部的铺陈、对话、动作、心理和过渡由作者自然组织。
4. Function 场景应完成对应的核心行动和状态变化；ending 完成尚未完成的结局动作，并展示冲突结果和最终状态。Function 与 ending 不重复承担同一核心事件。
5. 以 seed、Function、题材实现和关系状态作为主线骨架。正文可以补充不改变主线结果的配角、局部阻碍、日常行动、对话、心理和环境细节；这些补充不得成为解决核心冲突的临时关键人物、证据、资源或援助，也不得改变 Function 结果、关系上界和结局方向。
6. 用具体动作、对话、证据、物件变化、身体反应和可观察后果表现情绪与关系，避免抽象总结、机械重复、同义反复和注水。信息分散在已有场景；最终供述或告白只补当前必要的缺口，不复述完整案情或全部动机。
7. LiteraryDesign 是表达和局部展开依据；不得用文学呈现替换核心行动，或改写 Function 结果、关系终态和结局方向。"""


STORY_VALIDATOR_PROMPT = """你是 Story Validator。只依据原始 user_request、seed、Function 约束、scene_plan、scene_developments、ending_target、chinese_char_count 和正文，判断是否可以导出，只输出 JSON：
{"user_request_ok":true,"causal_constraints_ok":true,"character_consistency_ok":true,"ending_ok":true,"unsupported_solution_ok":true,"overall_ok":true,"repairable":false,"issues":[],"ending_evidence":[{"requirement_index":0,"scene_id":"S9","evidence":"实际结局行动与后果"}],"function_execution_evidence":[{"segment_index":1,"function_name":"FUNCTION","scene_id":"S1","evidence":"实际行动及状态后果","status":"PASS"}]}

逐项检查：
0. 固定输入（source_outline、function_chain、function_constraints、scene_plan、ending_target、ending）是否自相矛盾，尤其是否要求互斥行动/终态或让同一核心事件由 Function 和 ending 各完成一次。若矛盾，overall_ok=false、repairable=false，并说明具体冲突；不能靠改正文或改输入修复。
1. user_request_ok：正文是否实现原始 user_request。原始请求优先；不得从历史 Pattern 或模型推断新增核心冲突、关系阶段或结局义务。无明确要求时为 true。
2. `function_execution_evidence` 对每个目标 Function 恰好一项，严格按链顺序；原样复制 segment_index/function_name，scene_id 必须是对应 Function 场景而非 ending。status 只能为 PASS/MISSING；只有正文实际写出关键行动及状态后果才是 PASS，计划复述、抽象意图或仅作准备均为 MISSING。evidence 记录正文证据，不运行 Observer/Matcher。
3. causal_constraints_ok 与 character_consistency_ok：Function 行动、required_effects、状态和因果是否按序发生；人物身份、动机、角色位置、关系和代价是否有输入及正文证据支持，不能张冠李戴或无依据升级关系。goal/motivation 是开场驱动力，不是必须完成的结局义务。
4. ending_ok：最后独立 ending 是否完成 ending_target 的 resolution_actions、ending_must_show、conflict_resolution 和 required_final_state，并展示同尺度的直接后果；不能停在准备、决定或新的危险。ending_evidence 只是诊断记录，不要求与 must_show 一一对应。允许制度、阵营和利益余波存在，但不能以个人结果代偿集体/系统主线。不得重演 Function 已完成的核心行动。
5. unsupported_solution_ok：是否新增输入之外的临时能力、人物、线索、援助、证据、规则或解决方案；没有则为 true。
6. 若原始 user_request 明确提出最低字数，才根据 chinese_char_count 检查该用户要求；系统建议的 10000 字以上不构成门槛，未明确提出时忽略长度，不得自行设定门槛。只报告阻止导出的具体问题。固定输入一致时，正文遗漏、偏离、因果不足或无依据解决方案均为 repairable=true；通过时 repairable=false。literary_design 只影响表达，文学质量和文风偏好不得导致机械失败。"""

SCENE_PLAN_PROMPT += " 事件所有权规则：每个核心行动只能在一个 Function 或 ending 场景实际发生；Function 已完成的 resolution_action，ending 只能回收直接后果、余波或其他尚未完成的结局动作，不得重演。"
