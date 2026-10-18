# 历史素材库实施状态

## 已部署：清理及名称预览；其余为代码阶段

- 历史成片清理预览：三个自然月、已发布/未发布/全部，保护近期更新的成片、正在处理的分组及待发布任务。
- 清理将生成文件原子移动到同盘 `_recoverable_cleanup/<batch>`，归档分组及关联任务/剪辑行，保留原录像；原录像解除旧分组并设为不自动重剪。
- 每批保存数据库备份和逐行/逐文件日志；可恢复文件、分组及关联记录。引用变化时要求重新预览。
- 前端增加“历史素材库”，提供清理预览、可恢复清理、恢复批次及商品名称候选表。
- 录像分辨率只读检查接口：1080×1920/1920×1080为最低可用尺寸；探测失败标记复核，不归类为低清删除候选。
- 商品名称提取、当前款口播证据判定、按名称/颜色/特征构建目录及稳定片段ID与源时间清单。
- 边界识别提示词区分当前展示、历史提及、未来预告及摘戴过程。

## 仍需完成

- 低于1080P录像的可恢复弃用与恢复入口已上线；仅支持未关联、未排队且未在处理的本机录像。
- 将分辨率盘点接入前端录像多选及后台批任务，支持进度和断点续跑。
- 用实际SRT逐句核对模型 current_evidence；串联视觉核验、摘戴拆分及归档计划。
- 执行单款片段精确切割、输出校验、文件SHA256与独立片段索引持久化。
- 同款历史素材检索、推广视频/回忆录/合集生成。
- 已完成生产清理预览、低清分辨率检查及页面按钮验收；实际按发型切片仍未完成。未清理、删除或切割任何生产素材。

## 恢复与空间

可恢复清理暂不释放同盘空间；永久释放必须另设明确的保留期限与最终清空操作。本版本没有自动永久删除逻辑。
发布记录从业务列表归档到批次日志，恢复时一起恢复，避免悬空分组外键。

## 验证

本地定向测试覆盖自然月边界、文件和数据库恢复、原录像保留、名称示例、历史口播排除、分辨率方向、稳定片段ID、多链接同名和重叠区间。
前端构建通过。以上是代码层验证，不代表生产验收完成。

## 2026-10-17 生产发布记录

- 页面：`http://10.190.0.203:8899/history-library/`，原前端右下角增加入口。
- 原前端仅保留编译产物，采用独立Vite入口部署，未替换原业务JS/CSS。
- 部署版本：cb65261；三种筛选预览、发型名列表、批次列表、静态资源均验证正常；无预览凭据的清理请求返回422，非法恢复批次返回409。
- 浏览器预览显示53个候选旧分组、0.00GB可移动文件；候选随后台处理及文件权限重新核验可能变化。
- 生产备份：`C:\Users\neo\douyin_backend\codex_rollbacks\history-library-68e588b-20261018-091813`（目录时间来自服务器）。包含数据库备份、原文件、SHA256清单及rollback.py。
- 回退：在安全窗口运行该目录rollback.py后重启后台；脚本检测生产文件漂移时停止，避免覆盖后续修改。
- 未执行生产清理；分辨率检查API仅只读，批量弃用和按款切片尚未上线。名称候选不是已确认的素材身份。

### 发型名提取修复 23b80e5

- 保留括号前的名称边界，避免把括号后的商品描述拼到名称上；支持【宝宝冰蓝】、【西梅乌龙】等独立名称。
- 增加真实标题回归样例；名称仍为候选，不能单独证明录像中正在展示该款。
- 定向测试：13 passed（商品名称、片段计划、可恢复历史清理）。
- 生产原文件与带SHA256漂移保护的rollback.py：`C:\Users\neo\douyin_backend\codex_rollbacks\catalogue-names-23b80e5-20261018-094252`。回退后需重启后台。
- 未移动录像、未执行历史清理；低清弃用与实际分段归档仍待实现。

## 低清录像可恢复弃用

- 新增 recording_resolution.py：每批1至100个录像ID，只操作存储根目录内的本地完整源文件；跳过分组/片段引用、同名共享来源、待处理/处理中、已删除和探测失败记录。
- 预览与执行分别探测；执行在数据库写锁内重新核对文件大小/修改时间及记录状态，文件移入独立低清恢复目录。仅修改 local_deleted、clipped、transcribed、skip_reason，原值保存在持久化批次日志。
- 恢复前检查整批文件与记录冲突；支持 prepared 日志覆盖移动后数据库未提交的中断。日志状态为 restored 后不允许重复恢复。
- 页面新增录像ID检查、低清弃用、批次恢复；同盘移动不会立即释放空间。已关联分组与排队中的录像暂不支持直接弃用。
- 本次定向测试19项通过，独立前端构建通过。未批量弃用生产录像。按发型实际切片仍待实现。

### 生产发布与兼容修复

- 版本4229ed9及补丁e381664已同步GitHub并部署；补丁复用生产现有直播间子目录解析器，并显式关闭SQLite连接，避免Windows文件句柄残留。
- 初次备份：`C:\Users\neo\douyin_backend\codex_rollbacks\low-resolution-4229ed9-20261018-095036`。
- 补丁备份：`C:\Users\neo\douyin_backend\codex_rollbacks\low-resolution-e381664-20261018-095202`。每个目录含数据库备份、原文件、SHA256清单、带漂移检查的rollback.py；回退依次先补丁、再初次版本，之后重启后台。数据库没有结构变化，不需要覆盖实时数据库。
- 21项本地定向测试通过；Windows临时数据库/模拟低清文件完成弃用、恢复、临时目录删除的独立往返验证，未操作生产媒体。
- 初版生产接口/前端资源HTTP200，空ID检查422，无效弃用/恢复409；补丁后继续核验真实录像分辨率。

- 补丁后生产及浏览器只读验收：录像45261为1088×1920（保留），45253为240×422（低清候选，0.11GB），未点击弃用。恢复批次仍为空。页面已显示检查结果，截图保存在工作区 outputs/low-resolution-production.png。

## 发型口播时间线与原字幕核验

- 新增 wig_transcript_evidence.py：解析原始SRT毫秒时间，按商品库提取名称提及；同名多链接保留所有商品记录ID，历史/未来/问题提及不自动命名。
- 分段计划必须核验 current_evidence 实际出现在源时间窗口内；保留相邻原话上下文，不接受跨长停顿拼句；无字幕核验即使视觉布尔标志为真也不能成为ready。
- 页面新增单条录像的只读口播时间线（最多展示500处名称提及），过滤到该直播间及全局商品；不调用模型、不生成片段、不持久化归档。
- 26项定向测试及独立前端构建通过。连续摘戴视觉核验、精确切片及归档索引仍待接通；口播候选不代表视觉身份或完整分段已确认。

### 口播证据生产部署

- 部署代码e405074；生产备份：`C:\Users\neo\douyin_backend\codex_rollbacks\transcript-e405074-20261018-101207`，含数据库备份、原文件、SHA256清单和rollback.py。回退文件后重启后台，脚本遇到后续修改会停止。
- 原有录制系统编译资源未替换，仅更新独立历史素材库页面及新增/相关模块。无数据库结构变化。

### 原始录像验收及名称兼容补丁

- fab1f2f复用生产resolve_srt_file，支持“原片在直播间子目录、字幕在根目录”的真实布局；备份在`C:\Users\neo\douyin_backend\codex_rollbacks\transcript-fab1f2f-20261018-101417`。
- d53b7cd排除单独颜色词作发型名称：“黑色 昭和美人”提取为“昭和美人”；备份在`C:\Users\neo\douyin_backend\codex_rollbacks\transcript-names-d53b7cd-20261018-101525`。28项定向测试通过。
- 生产录像45259读取2162条字幕；初版26处商品提及中发现颜色词误命名并修复。真实“夺回人生过了吗”“夺回已过”被保留为历史/问题提及，未认作当前款。浏览器已验证查询与原时间线显示，补丁后复验。
- 回退按相反部署顺序执行每个目录rollback.py并重启后台；校验发现文件漂移时停止，不覆盖后续修改。未切割、移动或删除生产录像。

- 最终生产复验HTTP200：录像45259的2162条字幕产生21处名称提及；已无“黑色”伪发型名，4处夺回/人生历史、未来或疑问提及均未提升为当前介绍候选。仅只读查询，没有生产切片或媒体写入。

## 独立分段计划索引

- 新增 wig_library_index.py；数据库位于存储目录 `_wig_library/index.sqlite`，不修改业务库表结构。
- 单条登记通过ffprobe核对视频参数并流式计算SHA256，校验期间源文件变化即停止。以内容SHA256作为asset_id，分别保存来源主机、路径、录像ID、直播间和校验时间；登记不复制媒体，不等于备份。
- 分段计划记录原始SRT校验值、源时间、发型/商品候选、口播核验及复核状态。按asset_id与源时间生成稳定片段ID；改名保存新计划版本，旧版本不覆盖。
- 保存幂等，撤销/恢复只更新计划状态并追加审计事件，撤销后重复提交不会自动恢复；不删除原片或旧计划。
- 页面提供单条手动候选区间登记和最近100个计划查询/撤销/恢复；客户端不能提交视觉确认标志，保存后仍待视觉复核，不会自动出片。自动视觉分段、分段文件生成与历史混剪仍未接通。
- 34项定向测试通过，独立前端构建通过。GPU调度地址及密钥在当前环境中均未配置，本轮不启动视觉推理。

### 独立索引生产发布与验收

- 代码c6e5b46已部署，备份目录：`C:\Users\neo\douyin_backend\codex_rollbacks\library-index-c6e5b46-20261018-102429`，含业务数据库备份、被替换文件、SHA256清单与rollback.py。回退文件后重启后台；保留独立索引元数据，不自动删除已登记计划。
- Windows临时目录内完成内容登记、计划幂等保存、撤销、恢复和临时目录清理。生产媒体没有修改，未创建测试生产计划。
- 生产最近计划接口HTTP200（空列表）；空区间和无效计划ID返回409，伪造visual_verified返回422；原口播接口仍为2162条字幕、21处提及。
- 新前端JS/CSS均HTTP200，浏览器确认登记/查询入口可用；截图位于工作区outputs/library-index-production.png。源文件完整SHA256登记的真实大录像耗时尚未验收。

## 精确分段执行与可恢复导出批次

- 新增wig_archive_render.py：CPU重编码按源时间切割，不使用GPU；不复制关键帧导致时间外内容混入。原录像保留，原片尺寸用于归档素材，广告2K输出仍沿用广告流水线。
- 执行前要求索引中的计划有效、全部区间身份已核验且无重叠，校验源SHA256；忽略客户端输出路径，输出按名称+颜色+特征分目录。页面候选计划不能伪造视觉确认。
- 临时目录生成全部片段，核验时长及输出SHA256后，连同原片主机/路径/流信息、源时间、字幕SHA256、商品/发型证据一起原子落位。
- 批次撤回移动至可恢复目录，完整批次可恢复；重复提交返回同一批次并检查文件。支持落位后日志未提交的恢复、撤回中断重试；失败临时结果保留，不覆盖原文件。
- 新增导出预览/执行/列表/撤回/恢复API及页面入口。此处只生成按款归档素材，不自动发布、不生成广告成片。
- 38项定向测试通过。合成红/蓝视频使用长关键帧间隔，在非关键帧时间分别精确切出1.4秒片段，逐帧颜色及音视频时长检查通过，原片SHA256未变；完成幂等、撤回、恢复、损坏冲突和中断恢复验证。这不证明真实假发身份识别准确率。
- 生产身份视觉核验、自动分款仍待接通；当前人工登记计划均待视觉核验，不会直接出片。

- 失败重试：完整保留旧临时目录和旧日志，再以同一批次身份执行新尝试；重试准备阶段中断可继续。新增合成失败注入测试，最终39项定向测试通过。

### 切片执行层生产部署验收

- 初版ac36215备份：`C:\Users\neo\douyin_backend\codex_rollbacks\archive-render-ac36215-20261018-104231`；失败重试补丁2f28c7c备份：`C:\Users\neo\douyin_backend\codex_rollbacks\archive-retry-2f28c7c-20261018-104413`。含数据库、原文件、SHA256及rollback.py；如独立索引已存在，初版部署也备份其数据库。
- 文件回退按相反部署顺序执行对应rollback.py后重启后台。切片批次使用页面撤回/恢复，不覆盖原录像；日志和历史尝试保留。
- Windows临时合成视频实际验证：非关键帧切出1.4秒片段、逐帧颜色、时长、来源SHA256、撤回/恢复、失败注入及重试、旧结果保留，全部通过。临时目录已清理，生产媒体未修改。
- 生产导出列表HTTP200且为空；无效计划的预览/导出/恢复/重试均409；前端JS/CSS均200，浏览器显示原片分段区域。
- 当前生产候选计划没有视觉确认，未批量切割真实录像。连续摘戴视觉测试仍待GPU执行授权或AID调度配置。

## 用户授权的一次连续摘戴视觉实验

- 用户明确允许临时使用203现有Qwen服务，独立测试一个不超过10分钟的片段；选录像45259的900–1500秒。没有改变生产识别配置，没有批量出片。
- 测试目录：`C:\Users\neo\douyin_backend\codex_rollbacks\continuous-wig-test-20261018-104632`。保存范围、逐帧图片、源时间、帧SHA256、原始响应及逐秒边界图；代码位于scripts/validation/continuous_wig_shadow.py与score_continuous_wig.py。
- 24帧粗采样耗时292.98秒，佩戴状态与人工帧标签严格一致17帧；990秒底发被判稳定佩戴（0.94）。同一次实验的3个问题帧独立窗口对照耗时52.16秒，990秒仍误判稳定佩戴（0.95），缩小批次未解决核心问题。
- 多处梳理/整理被误判过渡，深色长发阶段签名漂移，独立单帧对发色/刘海也不稳定。本样本不证明实物同款回戴，不能宣布该项通过，不能据此推算生产准确率或确认SKU。
- 结论：现有4B静态窗口服务未通过本次自动分款验收；未将实验输出写回生产计划、未用于生产切片。下一步需要可靠的佩戴状态与连续动作跟踪，不能仅以颜色/长度签名及置信度合并同款。
- 详细人工复核报告保存在工作区outputs/连续摘戴视觉测试评估.md；原始脸部画面与模型响应留在203及本机，不纳入代码仓库。

## Qwen3.5-4B 独立升级对照准备

- 现有生产服务实际为Qwen3-VL-4B-Instruct-FP8；候选选官方Qwen/Qwen3.5-4B，固定提交851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a。候选目录C:\douyin_login\qwen35_shadow，不覆盖生产模型、服务及配置。
- 用户单独明确授权这次GPU升级对照实验。范围为录像45259的900–1500秒内问题帧和连续摘戴边界；不批量出片，不回写商品/分款结果。
- 新增固定清单下载、文件校验和独立测试脚本。203访问Hugging Face超时，改用Qwen的ModelScope镜像传输，但所有文件仍必须匹配固定官方提交的校验值；镜像LICENSE文本不同，保留拒收文件并从固定HF版本补齐校验通过的原文件。下载完成前不加载模型。
- 下载恢复与错误校验测试2项通过；运行时已确认transformers支持qwen3_5，但尚不能据此声称推理成功或识别改善。
- 回退方式：本实验不修改生产识别配置，保持候选离线即可继续使用原服务；保留候选模型、原始响应、帧证据及失败日志，不删除原录像。后续生产切换需另行完成备份和验证。

### Qwen3.5 升级对照实测结果

- 固定官方清单13个文件均校验通过，候选已完整下载到独立目录；没有修改生产服务。测试目录C:\douyin_login\qwen35_shadow\comparison-20261018-113222（服务器本地时间）。
- RTX4080SUPER，torch2.11.0+cu128 / transformers5.3.0，BF16、SDPA；加载23.69秒，7组总耗时170.58秒，峰值分配9398MiB、预留10010MiB。缺少线性注意力快速组件，回退torch实现；processor提示enable_thinking参数被忽略，因此不声称已显式关闭思考。
- 相同旧提示词、448边长的三个问题帧：990秒仍误判稳定佩戴（0.95）；1170秒稳定佩戴；1320秒为浅棕长发但刘海仍误判。不能宣称单纯换模型解决底发识别。
- 新连续提示词、768边长的四组各4帧：部分戴上动作能识别；988/990秒底发被标taking_off而非完成摘下；1271秒实际摘下过程仍标wearing。部分理由写无法确认却给出wearing，结构化标签与理由不一致。此组同时改变提示词与分辨率，不能把收益全部归因于模型升级。
- 同款实物回戴、真实换款及商品SKU尚无充分验证，不给出生产准确率；本次未通过自动分款验收，候选保持离线，没有切换生产、没有切割真实媒体。原始响应、19帧证据和状态留在独立测试目录；本机副本outputs/qwen35-comparison/status.json不纳入代码仓库。
- 进程正常退出并释放候选模型引用；原服务health正常且loaded=false，后台HTTP200。WDDM整卡显存会随其他桌面进程变化，health空闲显存与nvidia-smi值有差异，不能用该健康字段证明整卡已完全空闲。

## 连续状态证据离线复核

- 新增独立wig_sequence_evidence模块与audit_qwen_sequence工具，仅分析已保存的模型JSON，不调用GPU、不替换生产识别、不切片。
- 根因之一是输出状态与理由不一致：例如理由说无法确认但状态wearing，或理由描述摘完后而状态仍taking_off。模块保留原始行与源时间，输出明确冲突；不擅自把冲突标签改成no_wig。
- 头部状态与手持假发分开，holding_only不推定头上无假发；底发/发网/动作过渡不生成商品颜色。摘戴或大于2秒的采样空档分开候选观察段，外观相同不证明实物同款回戴。观察段不扩张成完整可剪辑时间边界。
- 现有Qwen3.5四组连续输出离线复核发现6处标签/理由冲突。这只是模型输出一致性分析，不是自动修正准确率；错误但自洽的模型输出仍可能漏检。
- 8项定向测试通过，覆盖完成摘下与状态冲突、底发/发网及手持物隔离、同外观跨摘戴/采样空档、非法与重复时间、主播不可见。现有视觉窗口测试保持通过。
- 模块尚未接入生产路由，生产行为不变；回退可直接停止使用离线工具。后续需连续标注样本验证，不能凭此复核自动赋予visual_verified或SKU确认。

### 连续区间的口播与商品候选关联

- 复用现有原始字幕解析、商品发型名称提取和当前介绍识别，离线工具可同时输入--srt与--catalogue，并记录两份输入校验值。
- 仅关联观察区间内完整包含的字幕，不跨摘戴/空档传播名称，不把过渡期提名直接套到下一款。未知仍保留未知，不猜测延伸边界。
- 夺回/人生等复合名称沿用同一正式名；同名不同链接完整保留多个商品候选。不同当前名称保留冲突，名称相同仅说明文本候选一致，不确认实物同款、SKU或可剪辑状态。
- 15项定向测试通过，增加复合别名与不同链接、跨过渡名称、历史提及、多当前名称冲突及不修改输入验证。已有Qwen输出离线重放仍为4组、6处状态冲突，无新增GPU调用；未接入生产路由。

## 真实字幕复核与现成方案评估

- 只读取得录像45259原字幕与当前直播间172条启用商品快照，保存在工作区outputs/qwen35-comparison，原字幕及业务数据未改。4组连续测试观察跨度太短，没有覆盖完整介绍，名称关联仍为空；没有将几秒观察外推成整段身份。
- 900–1500秒字幕含“才发轻轻”“虎破精灵”等疑似ASR名称误听。前者不强行认定财阀千金；后者可通过同音检索获得琥珀精灵候选。未听原音确认，候选不得直接当作当前佩戴或SKU证据。
- 触发现成方案复用评估：旧Qwen静态窗口、独立单帧、Qwen3.5连续对照仍未解决底发/动作可靠识别。后续不继续同类提示词微调作为唯一方案。
- 官方方案来源：SAM2 https://github.com/facebookresearch/sam2 支持视频对象跟踪，官方Windows建议WSL；Cutie https://github.com/hkchengrex/Cutie 可作为视频对象分割备选。均不自带商品SKU或假发佩戴语义，不能以掩码跟踪成功替代实物同一验证；未安装或运行，当前203显存/兼容性未验证。优先评估SAM2小模型与Qwen分工，备选Cutie；需要连续标注摘戴、遮挡、复戴和真正换款样本，先验证头部与手持假发能否持续分开，错跟/重新出现身份不确定时不得自动合并。
- CPU名称检索复用pypinyin https://github.com/mozillazg/python-pinyin ，本机独立虚拟环境固定0.55.0；脚本requirements-phonetic.txt记录版本，不修改生产依赖。同音无声调仅生成待复核候选，不改字幕、不确认名称、不回写绑定。官方API可用已实测，当前原生Windows生产未测试该组件；无GPU与服务费用。回退为停用独立脚本/环境，所有原始资料保留。
- 真实复核暴露最小解析缺陷：“免醒发仿递针-天蝎座”此前提取成“免醒发”。补充规格词过滤后恢复天蝎座/焦糖栗子等真实名称，未部署生产。修复后本10分钟字幕同音候选8处，涉及4个名称；这是检索候选数量，不是确认的商品或发型数。
- 17项原有/新增解析与区间测试通过，另2项真实pypinyin测试通过，覆盖不同商品ID不合并、原句不修改、标点不跨接、非同音与原本正确名称不替换。所有变更尚处独立验证阶段，生产识别配置不变。

### 名称规格解析修复生产发布

- d4b24a5中的wig_catalog_names.py单文件已部署203；其余同音检索、连续状态模块及Qwen候选保持独立，未加入生产路径。替换前确认发布/千川生成运行任务均0且文件SHA256与预期旧版一致。
- 备份目录C:\Users\neo\douyin_backend\codex_rollbacks\names-d4b24a5-20261018-115247（服务器时间），含旧文件、数据库快照、前后SHA256清单、rollback.py及post-deploy.json。业务数据库未修改；不可把快照覆盖到后续新数据上。
- 新文件SHA256 af59b408d8a4b62ea788e042149dee284f66619d836c41b4a19f2a49e695227e；后台计划任务重启后原首页、历史素材页、45259口播证据接口均HTTP200。接口2162条字幕、17条商品提及，无“免醒发”伪发型名称。
- 真实商品582/627解析天蝎座，586焦糖栗子系列，587白金栗子。只修复运行时名称解析，不重命名既有媒体、不修改商品URL或已保存分段。
- 回退：空闲时执行本目录rollback.py恢复旧解析文件，再重启Uvicorn8899。脚本校验目标未漂移及备份SHA256；已在独立临时目录验证能恢复旧文件、拒绝覆盖漂移文件，未对生产执行回退。

## 同音名称复核页面生产上线

- c085c3a提供可用前端入口与只读POST /api/history-library/recordings/{id}/homophone-review，指定原始时间最多600秒。复用现有录像路径与原始字幕校验，当前直播间启用商品完整保留，不按同名合并记录。
- 历史素材页展示原字幕、疑似误听、名称和各商品候选；仅http/https链接可点，无有效链接明确提示。候选不自动改名、切片、挂车、保存身份或触发GPU。
- pypinyin0.55.0从PyPI官方元数据验证wheel SHA256后解包到独立text-review-runtime/vendor，通过Python -I子进程运行，未安装进生产Python依赖。串行CPU任务、30秒超时、2MiB输入上限及每次1000字幕/5000商品上限；超时/缺组件明确报错，不返回空成功。
- 19项定向测试与2项独立真实pypinyin测试通过，前端构建成功。生产页面、JS/CSS及真实45259的900–1500秒接口HTTP200，返回8处线索，超600秒返回409；浏览器实际操作已显示相同结果。
- 本次实际候选的商品链接均为空（589、705、593、734、739等），页面展示“未绑定有效链接”。名称找到不等于链接找回；仍需商品来源恢复真实链接，不能按名称猜挂车地址。
- 部署前运行发布/生成任务0、路由文件SHA256符合预期。备份C:\Users\neo\douyin_backend\codex_rollbacks\text-review-c085c3a-20261018-120043含旧文件、数据库快照、SHA256清单、rollback.py与post-deploy.json。原主站前端保留，只更新历史素材独立页面与对应后端。
- 回退：空闲时执行该目录rollback.py，再重启Uvicorn8899。文件漂移和原备份均校验；独立文本运行目录移至备份disabled-runtime保留。已在临时镜像目录验证全部9项部署文件回退及运行目录保留；没有对生产执行回退，不自动恢复数据库快照。
- 浏览器截图位于本机outputs/homophone-review-production.png，原始字幕/商品快照与结果不提交GitHub。Qwen3.5候选保持离线，连续实物身份仍未验收。

## 商品链接手工编辑入口生产上线

- 用户明确：以百应店铺172575500为来源，同名不同链接正常，只对链接去重；找不到保持空白，提供手工编辑入口。Chrome已有登录店铺页已验证可见丝颜假发商品列表；本次没有以名称猜写缺失链接。
- 新增product_link_edit.py：仅更改product_url，保持名称及原平台编号；允许空值，拒绝重复链接、非法协议、凭证URL和过期编辑值。SQLite写事务串行检查，发布进行中不修改。每次真实编辑在F:\douyin_recordings\_product_link_edits保存修改前后值与prepared/applied/restored日志；支持条件撤销、重复撤销、拒绝覆盖后续编辑及避免恢复重复地址。
- 主商品库每行增加“填写链接/编辑链接”，弹窗保存及“撤销上次链接修改”。生产原主JS带有codex发布等未同步回源代码的补丁，因此没有整包替换；采用独立product-link-editor-1db524f.js加入口，原JS/CSS及历史素材入口保留。标准Products.vue源码及增量补丁也已入库，供后续统一构建；220预备构建源码已回退原状，未部署该整包。
- 10项定向Python测试通过；本机与220源码构建通过（未整体部署）；独立浏览器与测试数据库实际验证重复地址报错、同名不同地址保存、撤销恢复空白。生产739只做空值不变保存，返回changed=false；非法URL返回409，未写入测试链接。
- 生产首页、独立编辑JS与读取接口均HTTP200；浏览器真实739弹窗读取名称且链接为空。截图outputs/product-link-editor-production.png。此处验证编辑功能，不宣称挂车接受任意手工链接或模型身份已确认。
- 部署第一次检查发现3个生成任务活动，未修改文件；待5288/5289/5290在部署前均结束为-1后重新检查空闲并发布，没有中断这些任务或发起重跑。
- 备份C:\Users\neo\douyin_backend\codex_rollbacks\product-link-editor-1db524f-20261018-123316含四个文件清单、原文件、SHA256、数据库快照、rollback.py与验收记录。空闲时执行rollback.py并重启Uvicorn8899回退代码，用户商品编辑和日志保留；不要用旧数据库快照覆盖新数据。四文件回退已在独立临时目录验证通过。
- Git代码提交5e981c8、1db524f；独立临时测试服务已停止。当前5条缺失商品的历史链接未恢复，空值保留，用户可从主商品库手工填写。

### 2026-10-17 发布商品链接修复

- 发布调度此前会在 product_url 为空时回退到平台商品 ID，单商品路径也直接传 ID。改为执行时读取所选商品当前 URL；禁止用 ID 拼造地址，任一所选商品缺链接时在创建发布器前返回可操作错误，不自动网络重试。
- 同名不同链接保持独立；按选择顺序去重链接；显式无车发布及其他平台保持原路径。历史裸 ID 仅在商品库能唯一解析到已存 URL 时兼容。
- 验证：独立环境 18 项测试通过，覆盖调度任务状态、发布器未启动、无车/其他平台、同名商品、时长规则。测试数据库和发布器均为替身，无实际发布或通知。
- 生产应用使用 scripts/patch_publish_product_links.py 对新读取的源文件定点补丁，保留生产其他差异；部署前保存源文件 SHA、SQLite 一致性快照、逐文件校验和与条件回滚脚本。回滚只恢复代码，不覆盖生产数据库。
- 限制：URL 语法校验不代表百应商品仍有效或该账号可挂车；未做真实对外发布测试。

生产验证补记：已部署 960b4e0 的发布链接逻辑。备份位于 Windows203 `C:\Users\neo\douyin_backend\codex_rollbacks\publish-links-960b4e0-20261018-125805`（目录使用服务器本地时间）。含数据库快照、原文件、SHA 清单和条件回滚脚本；回滚在临时镜像目录完整演练通过。重启后 /health ok，商品739链接编辑 GET 200；生产 Python 环境运行4项隔离发布状态测试通过，不触发真实发布/通知。只读检查待发布任务12181、12182各可解析3条已存链接，未修改或重试任务。Windows 测试夹具显式关闭 SQLite 连接，避免临时文件清理被占用。链接可访问性及账号挂车权限仍需实际业务验证。

### 2026-10-17 挂车失败传播修复

- 确认生产 _attach_product 在入口缺失、链接未通过校验、未搜索到商品及异常时会返回或吞错，调用方仍可进入发布。改为抛出明确错误；结束编辑需等对话框关闭，未出现确认对话框不再凭空认定添加成功。保留原有浏览器定位与点击方式。
- 保留既有最多5件的约束，改为明确提示超出数量，取消静默截断；链接解析阶段提前检查，独立发布器入口也检查。
- 验证：27项针对性测试通过，包括6类添加失败、完成编辑、最多5件、同名链接和发布调度。均使用替代页面或临时数据库，无实际发布。
- 限制：没有登录真实创作者页面测试。本实现确认的是现有编辑对话框完成路径；平台若改为无对话框直接挂车，会报错等待排查，不能把未见对话框当作挂车成功。未新增视频质量评分门禁。

挂车修复生产验证：c1e9dcf 已部署203，保留生产 publisher 的其他差异。备份 `C:\Users\neo\douyin_backend\codex_rollbacks\attachment-c1e9dcf-20261018-131033` 含两文件原版、SHA、一致性数据库快照及条件回滚脚本。部署前确认发布与剪辑运行数均为0；重启后健康检查正常、商品链接编辑接口200。用生产文件提取函数在替代页面执行8项离线场景通过，回滚在临时镜像目录验证通过；未发起真实发布、未更改商品或媒体数据。

### 2026-10-17 自动生成发布文案传递修复

- 根因：调度器临时补生成标题、描述、话题后只更新数据库，传给发布器的 task_ctx 仍为生成前快照，实际可能无标题或使用旧描述。修复为把本次解析得到的三项文案写入任务上下文，成功通知使用实际标题；保留用户已有文案与原有生成/失败策略。
- 回归先复现：多方案、旧格式、空结果回退3项均因发布器收到旧文案失败；修复后32项发布链路针对性测试通过。生成器、发布器和通知均替身，数据库隔离，未调用外部生成服务或发布。
- 生产使用定点补丁脚本 patch_publish_metadata.py，拒绝重复应用或锚点漂移，保留生产调度器其他差异。部署前备份及空闲检查沿用既有流程。

文案传递生产验证：e3d31f7 已部署203。备份 `C:\Users\neo\douyin_backend\codex_rollbacks\metadata-e3d31f7-20261018-132011` 含原调度器、SHA、数据库一致性快照、条件回滚脚本。使用生产调度器执行5种隔离文案场景通过，回滚临时镜像演练通过；/health正常、商品链接编辑接口200。测试数据库补齐生产独有版本字段及 video_path，保留生产版本重复发布提示逻辑，未重写为仓库较早实现。无真实发布、外部生成或商品/媒体数据修改。

### 2026-10-17 发布成片版本保留修复

- 根因：生产 resolve_video_path 先遍历分组其他版本，最后才看任务 video_path，可能把已选写实版替换成千川版；创建任务的生产 resolve_publish_video 也会在指定版本缺失时借用其他版本。独立临时文件测试复现任务成片覆盖、缺失时换版、迁移错选等6类失败。
- 修复：现存任务所选文件优先；缺失时仅恢复同文件名的历史位置，多个候选不猜；旧的版本名字面量严格解析对应版本。未指定文件时保留默认选择；显式版本缺失返回不可用及可用版本，不自动改选。迁移根路径、codex字段、生产其他函数原样保留。
- 本地45项针对性测试通过。补丁只替换两个选择函数，不覆盖整个生产文件。不移动、删除或重写成片与任务数据。
- 限制：文件名迁移仍依赖历史命名，不能以文件名证明视频内容或发型一致；有多个候选时需人工确认。未使用GPU或真实发布。

成片版本修复生产验证：cb0f4bc 已部署203。备份 `C:\Users\neo\douyin_backend\codex_rollbacks\video-selection-cb0f4bc-20261018-133431` 含原文件、SHA、一致性数据库快照、条件回滚脚本。生产实际解析模块运行9项临时文件场景通过；回滚仅在临时镜像演练通过。健康检查正常、链接编辑接口200。只读审计任务12181、12182均保持原选文件，新旧结果一致；未修改/重试任务，未发起真实发布。历史迁移根与codex映射均保留。

### 2026-10-17 发布页面文案填写修复

- 根因：标题及描述/话题填写异常只记警告，后续仍可能点击发布；描述框未清空即逐字追加，遇到已有内容会混入旧款描述。使用实际文案填写代码块和替代页面复现7项失败。
- 修复：标题及描述/话题填写异常向上抛出，终止本轮后续挂车/发布步骤；标题输入后读回与既有30字符截取值核对。有描述或话题需要填写时先清空编辑框再填入，避免追加残留内容。保留原有标题长度、话题数量与选择器，不新增视频质量门禁。
- 本地52项针对性测试通过；无真实浏览器发布或外部通知。补丁仅改变上述填写语句，保留生产浏览器参数及其他差异。
- 限制：未登录真实创作者页面验证；描述和话题测试模拟输入交互，并未证明平台最终审核或挂车有效性。描述与话题均空时仍沿用原有跳过描述的行为。

页面文案修复生产验证：e0a89e0 已部署203。备份 `C:\Users\neo\douyin_backend\codex_rollbacks\page-metadata-e0a89e0-20261018-134533` 含原文件、SHA、数据库一致性快照及条件回滚脚本。部署前发布及剪辑运行数均为0，重启后服务健康正常、商品链接编辑接口200。以生产实际填写代码块运行7项替代页面场景通过，回滚仅在临时镜像验证通过。未发起真实发布，未改商品、任务或媒体数据。

### 2026-10-17 主服务无响应根因与修复

- 现场：8899监听存在但健康、前端和商品编辑均超时，看门狗反复重启；CPU近空闲、内存63.8%，C盘约76GB/F盘约19.8GB可用。py-spy确认主线程在 director_matcher._fallback_match_single → _encode_subprocess_batch 的 threading.Lock等待，另一个线程在 subprocess._stdin_write；该同步调用发生在 async 回退匹配中，阻塞整个事件循环。
- 修复生产独有批量编码实现：回退匹配通过 asyncio.to_thread 执行；两处一次性子进程请求改用自动关闭删除的临时输入文件，保持同样的UTF-8 JSON行协议，避免Windows communicate(input=...)在管道写入时不能及时进入超时等待。保留已有常驻编码、熔断及匹配评分逻辑，不新增GPU调用。
- 测试：56项针对性回归通过，包括非读取子进程+1MiB请求仍按0.2秒超时结束、28万中文字符往返、事件循环在编码等待时仍可响应及补丁重复/漂移拒绝。均为CPU替身，不加载语义模型或提交GPU作业。
- 重启前发现director_status=1的9组、自编版2组，不能视为全部空闲；发布/千川运行数为0。为恢复已无响应服务需加载修复，保留数据库原状态和一致性快照，不手工批量重置、重试或宣称原任务成功。
- 其他观察：旧日志还有录像上传507、GPU剪辑500及本地媒体禁用错误；本修复不代表这些生产链路问题已解决。F盘余量较低，不自动清理媒体。

主服务修复生产验证：1a0be9f 已部署203，备份 `C:\Users\neo\douyin_backend\codex_rollbacks\matcher-nonblocking-1a0be9f-20261018-135617` 含两文件原版/SHA/数据库快照/条件回滚脚本。生产CPU协议测试通过（1MiB不读输入的子进程约0.219秒结束）；提取生产实际异步回退方法验证编码等待时事件循环可继续；回滚临时镜像验证通过。前端、健康及商品编辑均200，初次约0.14/0.37/0.08秒，后续健康0.178秒与1.035秒，多次复查正常，无人为提交GPU作业或发布。

剩余生产阻碍已核实：F盘约19.85GB，8877进程白名单环境项 BATCH_UPLOAD_LIMIT_GB=20、CLIP_MIN_FREE_GB=20、STORAGE_DIR=F:\douyin_recordings，因此上传/剪辑受空间保护拒绝。生产低盘剪辑错误分支在job_id定义前调用_clip_jobs.pop(job_id,None)，存在以500遮盖507的问题，待独立修复；未改阈值/重启GPU服务/删除媒体。只读根目录元数据扫描遇到849项访问拒绝，未修改ACL，不能把这些文件视为已丢失。

### 2026-10-18 磁盘应急迁移准备

- 只读盘点：F盘约19.84GiB/C盘约75.13GiB；clips约170.98GiB，director_outputs约53.77GiB，codex约1.46GiB，旧音频修复备份_opening_fix_audio_backup约0.715GiB/225文件。现有成片文件最老约9天，并非均符合三个月清理条件。
- 安全检查发现媒体路径解析拒绝跨根目录映射，因此不直接迁移成片目录、不放宽访问限制。先仅迁移不参与正常播放的旧音频修复备份到C盘，保留原F路径目录映射，供既有回退流程读取。此操作仅应急恢复少量余量，不代表批量生产容量已足够。
- 管理工具scripts/relocate_media_tree.py：逐文件SHA256校验复制，源变化/空间不足/嵌套链接时拒绝；映射验证后仅回收已验证的重复原件；记录逐文件清单与阶段。恢复时拒绝覆盖目标新内容，复制回F盘并保留C盘备份。6项临时文件测试通过，覆盖正常回退、映射失败、损坏复制、复制期间源变化与链接拒绝。

备份迁移完成：管理工具版本8c8eb40，Windows回退演练通过后，将225个旧音频修复备份共767236803字节迁到 `C:\Users\neo\douyin_backend\media_overflow\_opening_fix_audio_backup`。原 `F:\douyin_recordings\_opening_fix_audio_backup` 保留目录映射，逐文件SHA256一致；原录像/成片/商品/分组/发布任务未修改。C盘剩余约74.25GiB；F盘从19.837恢复20.551GiB，稍后20.424GiB，健康/前端分别200约0.106/0.046秒。未提交人工GPU作业或真实发布。

迁移记录及回退：`C:\Users\neo\douyin_backend\codex_rollbacks\storage-relocation-8c8eb40-20261018-141445`，包含管理工具、SQLite一致性快照、relocation.json逐文件清单、rollback.py及post-deploy.json。rollback.py校验C盘备份无新内容、F盘足够后复制回原处并恢复普通目录，保留C盘备份；不覆盖数据库。仅回收已验证重复副本，无媒体内容丢弃。现有6项迁移测试通过。F盘只略高于20GiB底线，长期批量生产仍需扩容或经平台兼容验证的成片分层迁移，不可把应急措施当容量问题完全解决。

### 2026-10-18 用户授权旧成片清理与临时片段跨机归档

- 用户明确授权清理三个月前生成的视频，录像源文件保留。截止2026-07-18当地零点（UTC06:00）。203主要生成池未发现早于截止的现存视频；220生产根目录和director_outputs初查约2224个候选/254.87GiB，尚需排除两端源录像和活跃引用。清理先同卷隔离，保留inode/大小/mtime清单和禁止覆盖新文件的回退；不按旧分组日期误删近期重生成版本。
- 222 SSH可达，disk2约5TB可用；220约895GiB可用。203有91个至少7天未修改且GPU登记已done/error的剪辑任务中间片段，共33.43GiB，先归档22个任务约8.199GiB。仅seg数字.mp4，保留最终成片/原录像/字幕；同时核对数据库引用，传输SHA256及回执验证后才回收源副本。
- 管理脚本archive_clip_temps.py和quarantine_generated_videos.py，6项隔离测试通过，含传输截断、回执/源变化、禁止原片名称、保留新文件及完整恢复。

跨机传输调整：自定义大块标准输出传输在Windows管道阻塞，222只生成首文件0字节partial目录，203源文件全部保留；已停止该传输，不把partial算归档成功。验证220可免交互SSH访问222，改用标准SFTP/scp -3 经220中转，并在222逐文件SHA校验、提交目录后才回收203副本。恢复工具restore_clip_temp_scp.py先复制到203新建暂存目录，再按原清单恢复，禁止覆盖现有生产文件。

220旧视频核对后清理实绩：524个旧生成视频/32.759GiB已从生产目录移至同卷隔离区 `/Users/claw/work/douyin-recorder/codex_rollbacks/generated-cleanup-3dce2df-20261018-143018`。两端recordings.filename及活跃发布引用的同名文件保留，近期重生成版本保留。原inode/大小/mtime逐项一致，原生产目录文件名已移除，manifest状态applied及rollback.py可用。客户端SSH等待超时发生在清理已提交之后；已独立读取服务器清单确认结果，未重复执行清理。隔离保留故220不增加可用容量；原录像未操作，分组可能仍含近期有效成片，未按旧组日期整组删除。

恢复链路：标准SFTP经220中转，已用独立CPU测试文件从222复制到203新暂存目录并恢复至专用测试目录成功。最终保留restore_clip_temp_scp.py，移除未采用的自定义流恢复工具。恢复支持重复调用和部分恢复，匹配旧内容可跳过，新内容拒绝覆盖，并用原子no-overwrite链接提交。13项归档/隔离/目录迁移测试通过。

执行完成复核：
- 220清理批次 protection-audit.json：源录像及活跃引用冲突0；隔离区仍保留524文件/32.759GiB，生产路径已移除。203根目录及主要生成池无可访问且符合截止的旧生成视频；不按旧分组创建时间删除近期重生成版本。
- 203→222首批已完成22个任务、460个seg中间文件，8.199GiB。222归档根 `/mnt/disk2/douyin-archive/203/clip-temp/20261018-3dce2df`；逐文件传输SHA256已验证，全部任务目录提交。源端 `C:\Users\neo\douyin_backend\codex_rollbacks\clip-temp-archive-3dce2df` 保存原清单/receipt/applied/result.json，复核全部回执指纹一致、计划源片段已移除。每次回收前重新核对主数据库所有媒体文件引用及GPU任务done/error状态。
- 222独立复核22任务/460文件/8.199GiB尺寸和清单一致，disk2剩约4992GiB。203 F盘剩27.862GiB，健康/前端/商品链接接口均200。保留原录像、成片与字幕，不更改发布/分组数据库；没有人为提交GPU任务或发布。
- 恢复测试：222经220向203暂存目录标准SFTP传输成功；Windows真实NTFS原子恢复/重复恢复通过。13项针对性归档/隔离/迁移测试通过。恢复脚本使用唯一暂存目录，拒绝覆盖新文件。
- 范围：220旧视频为可回退隔离，不计为物理释放；203临时片段为首批迁移8.199GiB，其他约25.2GiB候选未迁移。220作中转，实际长期归档在222；运行中临时目录仍留203。

### 2026-10-18 剩余冷剪辑中间片段迁移

- 用户要求继续后重新扫描203：69个GPU登记done/error且至少7天未修改的任务，1411个未被数据库源录像/成片/发布路径引用的seg中间文件，共25.231GiB；近期或受保护文件跳过7564项。已逐文件重新计算SHA256并保存remaining-plan.json，既有22任务不重复迁移。
- 新增受控批处理工具archive_clip_temps_scp_batch.py（220执行），最多两路SFTP中转，出现错误停止尚未开始的任务，已在进行的任务仅按完整校验流程完成。既有归档仅在清单一致且重新校验成功时复用，不覆盖不同内容；回收前再次检查任务状态与全库媒体引用。
- 15项针对性归档/隔离/目录迁移/批处理控制测试通过，包含并发上限及失败停止队列。无需重启平台或GPU服务，不提交GPU计算或发布任务。

剩余批次完成验证：本轮69任务/1411个片段/25.231GiB全部完成，无错误；与首批合计91任务/1871文件/33.430GiB。203逐项核对applied回执、源副本已回收、归档文件名与当前录像源文件名不相交；222独立核对91个提交目录的清单和文件尺寸。两端清单集合SHA256完全一致：4ebf338626aa7109499ac1718ac7e034fb63ec76be720373ea0724a3bf59f3b7。

203 F盘剩51.326GiB；健康/前端/商品链接编辑接口全部200。222 disk2约剩4967GiB。220实际执行批处理脚本SHA256与仓库一致（8ca3b43ca3818c41da3c745b3f570765b912799cf6d6b6ea0396ed47d8419665）。结果分别保存203归档管理目录与222归档根的remaining-result.json。保留所有计划、逐文件SHA、回执及恢复工具；没有移动/删除录像源文件、最终成片或字幕，没有重启服务、改保护阈值、提交GPU作业或触发发布。近期、活跃、被引用的临时文件仍留203；后续复用已归档中间片段需按清单从222恢复。

### 2026-10-18 Director output-spec compatibility fix

- Read-only post-storage audit found ordinary recording 45289 rejected with HTTP 500 before job creation; its exact server exception remains unresolved. No retry was submitted.
- Director/creative composition logs explicitly returned HTTP 422 because `qianchuan_output_spec` was null while the deployed GPU request schema requires a dictionary.
- Commit cce9795 changes the caller to send an empty dictionary for absent/null configuration and preserves explicit settings (including 1440x2560). Empty settings retain the worker's existing 1080x1920 default; this compatibility fix does not establish universal 2K output.
- Production was patched with a single checked replacement, preserving deployment drift. Backup: `C:\Users\neo\douyin_backend\codex_rollbacks\director-output-spec-20261018-154249`; contains previous source, SHA manifest, SQLite snapshot and conditional `rollback.py`. Rollback restores only code and requires an idle backend restart; never automatically restore the database snapshot.
- GitHub push completed before deployment. Backend Uvicorn8899 restarted only after a fresh database check found no running recording/group work. No GPU job or publishing task was submitted as a test.
- Targeted payload tests: 4 passed. Five broader existing GPU contract assertions also fail against the unmodified HEAD baseline; left unchanged and unresolved.
- Post-restart verification: production schema CPU validation passed; `/health`, frontend `/`, and `/api/history-library/products/739/link` all returned HTTP 200. Startup log confirms successful application startup. Initial requests during startup were unavailable, followed by successful bounded readiness check.

### 2026-10-18 Legacy clip low-disk admission patch (runtime pending)

- Deployed processor source and backend mirror referenced `job_id` in `_clip_jobs.pop()` before assigning it. Historical GPU stderr contains the matching `UnboundLocalError`; the exact October 18 recording 45289 request could not be correlated to that historical trace, so its individual cause remains unconfirmed.
- Minimal patch removes only that premature pop; admission still enforces the original free-space floor and returns HTTP 507. Existing jobs and the empty-segment HTTP 422 validation remain unchanged. Repository GPU implementation differs, so no wholesale file replacement was performed.
- Added `scripts/patch_clip_low_disk.py` and `tests/test_clip_low_disk_patch.py`. Ten targeted tests passed together with the director output-spec regression tests. Windows CRLF is retained; an initial source preflight refusal changed no production files.
- GitHub commits: 1d9537e and 141487e. Production source backup: `C:\Users\neo\douyin_backend\codex_rollbacks\clip-low-disk-20261018-155428`; both files have manifest-backed, drift-checked `rollback.py`. No database was changed.
- Both patched file SHA256: `ed822011036a726bd35605d677d489b1e13f573ef343cf02fbaedae1ad16ea4a`.
- GPU service was briefly idle but accepted new work before the final restart check. The guard correctly aborted before calling the watchdog restart endpoint. **Running PID 19956 has not loaded this patch; activation requires an idle maintenance restart.** No forced stop, new GPU test job or publishing action occurred.
- Post-write CPU execution of the deployed guard returned HTTP 507. GPU8877 health, backend8899 health/frontend and watchdog8878 status all returned HTTP 200; GPU PID remained 19956, confirming no restart.

### 2026-10-18 Complete media activity health reporting (repository only)

- Activation audit: GPU PID19956 reported all legacy clip/concat counters idle, but backend had 6 recording tasks and 12 group tasks active. Recent logs show group5305 entering director composition after voiceover. Existing health counters omit director, TTS and audio-concat activity; they cannot authorize a safe restart by themselves. No restart was attempted this round.
- Repository `gpu_service/main.py` now adds `media_jobs_active` counts for transcription, clips, TTS, audio concat, concat, classic concat and director. Unknown or missing states count as active, terminal historical jobs do not. Existing API fields are preserved. **This health change is not yet applied to production; the low-disk production source fix also remains unloaded in PID19956.**
- Four new CPU tests plus prior regression tests: 14 passed. No GPU workload was submitted.
- Further root cause: production `voice_director.py` forces non-Qianchuan audio shorter than 30 seconds through `local_media_slot("voice director audio stretch")` and local ffmpeg. This triggers the existing GPU-only execution protection, explaining creative failures for groups5259/5260. Protection remains enabled. A remote audio duration-adjustment design is still needed; no untested audio-path change was deployed.

### 2026-10-18 Remote-only voice merge and retiming (source staged)

- Production voice audio merge still used `/classic-concat-jobs`, downloaded MP4 and converted it to WAV on the control plane. Short non-Qianchuan narration additionally attempted local `atempo`, causing the GPU-only local-media guard failure.
- Backend now uses the existing `/audio-concat-jobs` WAV endpoint for merge and retiming; worker accepts optional `speed_ratio` constrained to 0.5..2.0, default1 preserves old clients. Short-audio timing retains existing stretch policy but scene durations now scale with the measured output duration for subtitle/shot alignment. No local ffmpeg or local-media-guard bypass remains in these methods.
- Downloads are streamed to a temporary file and validated as WAV before committing. Source audio is preserved on success/failure. Invalid output, unavailable endpoint, or an older worker silently ignoring speed returns failure; measured duration must match requested retiming within max(0.25s,3%).
- Commits bb97eb5 and0869654 pushed before their respective production source writes. All replacements were preflight-checked against the specific legacy methods, preserving unrelated deployment drift and CRLF. GPU source/mirror also receive the previously committed complete media health counters. No database edits.
- Backups: `C:\Users\neo\douyin_backend\codex_rollbacks\remote-audio-20261018-162339` (voice + both GPU source files) and `...\remote-audio-20261018-162521` (duration-validation follow-up). Each includes SHA manifests and conditional `rollback.py`; full rollback order is follow-up162521 first, then162339. The earlier clip-low-disk backup is a separate previous step. Rollback never overwrites source drift or restores a database.
- Current voice SHA256 e80730f31d11120b819b85082e3c226b1e1496898b8c1a85e4807a1eee19e632; both GPU files SHA2567254dd1b8ccfbf8903845a148315882d1c8abdabb639e216399c49a53a74c18a.
- 24 targeted tests passed, including real local CPU ffmpeg one-second WAV merge/retiming, mocked HTTP merge/error/old-worker scenarios, measured scene timing, Windows newline preservation, drift refusal and sandbox rollback. No new GPU workload or publication was submitted.
- Latest audit: 0 active recording tasks, 2 active group tasks; worker jobs/clip_jobs/tts_jobs/concat_jobs all have 0 nonterminal database records. Backend health/frontend and GPU health HTTP200. GPU PID19956 lacks the new health field, confirming pending activation. Maintenance mode gates future scheduling but does not prove already queued director tasks have drained; it was not enabled blindly.

### 2026-10-18 Production activation completed

- First attempt correctly stopped at the preflight when a new TTS job arrived; no maintenance/stop action occurred. Procedure was corrected to pause backend admission before draining already submitted remote work, avoiding an endless race with historical backfill.
- Versioned administrative procedure: `scripts/activate_remote_audio.py`; commits aa00c05 and2a715aa. It verifies staged source hashes, backs up SQLite, records active groups, preserves pre-existing maintenance state, pauses only the identified8899 service, waits for persistent queues and recent director jobs to finish, restarts GPU through watchdog8878, verifies new schema/health, and restores8899. It submits no new test/media/publishing jobs. Four maintenance guards plus earlier tests: 28 passed.
- Activation journal and database snapshot: `C:\Users\neo\douyin_backend\codex_rollbacks\audio-activation-20261018-164424`. Journal phase `complete`; GPU PID changed19956→22936. Actual OpenAPI exposes audio `speed_ratio` minimum0.5/maximum2.0; new complete media counters are live. The staged low-disk fix, complete health reporting and remote voice merge/retiming are now loaded.
- Captured creative groups5220/5221 changed creative_status1→0 via the existing startup recovery, preserving completed director/Qianchuan/classic versions. Startup also resumed existing recording work; no manual status resets or old database restore were performed.
- Post-start validation:8899 `/health`, frontend `/`, product739 link-editor endpoint,8877 `/health` and8899 `/api/gpu/status` all HTTP200. Maintenance false; normal background work resumed, with a TTS task visible in the new health counters.
- Audio source rollback remains ordered: run conditional rollback from remote-audio162521, then162339; restart services under the same drain procedure. The activation snapshot is evidence/recovery backup, never blindly restore it over newer business data.
- Remaining independent production failure: recording45298 created remote clip jobc16c4d7170f6484a, which ended `xfade merge failed`. Backend then emitted the misleading local-media prohibition because `_edit_via_gpu` returnedNone and variant processing reached its disabled local fallback. This is a worker render failure/error-propagation issue, not the now-fixed admission job-id error. No speculative xfade change or retry was submitted this round.
- Full new GPU audio rendering has not been submitted as an independent test; only existing authorized platform tasks resumed. Real browser publishing remains unverified.

### 2026-10-18 Crossfade audio fix

- Fresh production `_nvenc_xfade_merge` contained `acrossfade=d={fade}:o={off:.3f}:c1=tri:c2=tri`. FFmpeg documents `o` as an overlap boolean, not a timeline offset (https://ffmpeg.org/ffmpeg-filters.html#acrossfade). Historical worker stderr explicitly rejected `o=14.250` as an invalid boolean. The individual45298 trace was not found in these stale log files; the current production expression independently reproduces that same failure on CPU.
- Minimal classic-merge fix aligns each audio input to its declared video duration using resample/pad/trim and resets timestamps before crossfading the ends. Removed the invalid audio offset; the video xfade offset is preserved. Director and hard-cut implementations were not replaced. Backend editor now raises the worker job ID and original failure instead of returningNone into the prohibited local fallback.
- Commit fa4e27f pushed before production source writes. `scripts/prepare_xfade_deploy.py` generated targeted, drift-checked replacements in actual GPU source, mirror and backend editor. Backup: `C:\Users\neo\douyin_backend\codex_rollbacks\xfade-fix-20261018-170853`; SHA manifest and conditional rollback.py preserve prior remote-audio fixes. No database edits by the patch.
- Production GPU/mirror SHA2565f94f55ea3993a37c52cf56e7336700a7964677bcf30686477f72ef4999662b1; editor SHA256e4830ea8e682143722949cacc00e6b547015a585b59eea69dcff60c173f145af.
- Four new real CPU synthetic-media tests reproduce the legacy boolean failure, validate audio shorter/longer than video and a three-clip sequential merge. Measured A/V difference below80ms in fixtures. One new worker-error propagation test plus prior tests:33 passed. After generalizing the maintenance helper for manifest-provided hashes/rollback labels, the affected9 tests passed again. No direct GPU test/render/publishing job was submitted.
- Activation completed under `C:\Users\neo\douyin_backend\codex_rollbacks\xfade-activation-20261018-170926`; journal has database snapshot and2 captured control-plane groups. Remote queues drained before watchdog restart. GPU PID10200→6844, backend restored and maintenance false.
- Backend/GPU health, frontend and product739 link editor returned HTTP200. Existing platform clip jobdbc3ffec5ed94c19 (created09:09:54UTC after activation) passed the previous merge failure point and reached phase `final` with no error. It was resumed by the platform, not submitted as a new agent GPU test. Full artifact completion remains to be checked.
- Existing resumed taskdbc3ffec5ed94c19 subsequently completed `done`, error null. Output198638342bytes; read-only ffprobe: H.2641080x1920, video152.880s, AAC audio152.873991s, container bitrate10394471bps. This validates one actual production render through merge/final encoding after the fix, without an agent-submitted GPU workload. Whole-file stream durations differ about6ms; semantic/lip-sync quality was not visually reviewed.
- Important remaining scope: this classic artifact is1080x1920, so universal requested vertical2K1440x2560 remains incomplete. Successful rendering does not establish hairstyle identity correctness or real browser publishing readiness.

### 2026-10-18 Vertical 2K export unification

- Audit confirmed ordinary final video inherited1080x1920 intermediates, classic-concat single/multi exports normalized to1080, concat-jobs stream-copied old resolution, and the deployed director defaulted to1080x1920 despite supporting explicit2K. Backend editor output/legacy final filters were also1080. Existing production postprocess catches GPU-only exceptions and keeps the remote output, so no extra local4K pass was enabled.
- New video exports target1440x2560 while CLIP_W/H intermediate frames remain1080x1920. Ordinary final encode scales before ASS or on the no-subtitles branch. Director defaults to1440x2560; explicit supported requests remain honored. Classic-concat single input scales directly to2K; multi input retains1080 normalization then exports2K once. Concat-jobs now final-encodes2K instead of stream-copying legacy resolution. Existing H.264/AAC paths,25fps and10Mbps defaults retained; concat preserves normalized audio. Backend editor output dimensions/legacy filter follow2K. Historical artifacts and recordings are not batch rewritten.
- Commit8dcd73e pushed before deployment.43 targeted tests passed, including actual CPU single/multi concat and no-subtitle final1440x2560 H.264/AAC fixtures, subtitle ordering, low-resolution working frames, migration default behavior, existing audio/xfade/restart safeguards. Explicit1080 API requests remain backward compatible; no promise of detail reconstruction from scaling.
- First preflight correctly refused a whole-source match because GPU files contain3003CRLF lines plus10LF-only lines. No file was changed. Commit0b81432 adds raw context replacements preserving mixed line endings outside necessary edits;12 targeted2K/deployment tests then passed, including2 new newline/deployer tests. No shared GPU test was submitted.
- Production code backup: `C:\Users\neo\douyin_backend\codex_rollbacks\publish-2k-20261018-180030`, with originals, SHA manifest and conditional rollback.py. GPU actual/mirror SHA613d39de979aec594f9ff4d25b84d35cd06f3166ebea098d7d24c869b87cdfcf; backend editor SHAb0ce4064759c58a71b38c44a97a40905111060024f0ef33f8d4f8a662ad4561b.
- Activation journal/database snapshot: `C:\Users\neo\douyin_backend\codex_rollbacks\publish-2k-activation-20261018-180050`. Remote queues drained; GPU PID6844→10424; backend restarted. Final status request was reset during startup, after stage `services_started`;8899 guard log records an additional restart at18:01:11. The entire deployment was not repeated. Independent checks afterward all returned HTTP200 for GPU/backend health,frontend,product739 link editor and GPU status; maintenance false. Saved `post-check.json` and marked journal `complete_after_independent_verification`. The exact cause of this single startup connection reset was not conclusively established.
- Two existing platform tasks completed after activation without any new agent-submitted GPU workload:8eacb342997b49ab (10:01:46UTC) and9a696aa0066b451a (10:02:09UTC). Read-only ffprobe verified both H.2641440x2560 + AAC; durations152.68s/152.40s; sizes195254618/194897271bytes; average bitrate~10.23Mbps; video/audio whole-stream duration differences19ms/16ms. These metadata values meet the user-supplied vertical aspect/resolution/duration/size/minimum-bitrate limits. This does not certify platform ad review, image detail, hairstyle identity or semantic lip-sync.
- Rollback only this change with publish-2k180030/rollback.py after checking source drift, then drain/restart via the same maintenance procedure. Prior crossfade/audio fixes remain intact; never blindly restore the activation database snapshot.

### 2026-10-18 Follow-up: make new exports accessible through the API

- Post-export library check found recording_clips row14545 mapped to new2K job9a696aa0066b451a, but `/api/recording-clips/14545/download` returned404 `Clip file missing`. Direct SSH stat on the F-room path was denied, which alone did not establish application access failure; the API error and fresh route inspection established that downloads still hardcoded project/recordings instead of the editor/transcribe STORAGE_DIR configuration.
- Reused existing `_recording_file_path` in both recording-level and variant-level download routes, preferring configured storage, retaining exact legacy relative-path fallback. No file relocation, permission widening, alternate variant selection or database edits. Commitb78baed plus backend-only maintenance support15a947c pushed before production writes. Eight async route fixtures cover both roots, configured-root priority and true missing404; five activation guards include a full CPU backend-only maintenance fixture proving no GPU restart.13 affected tests passed.
- Main source backup: `C:\Users\neo\douyin_backend\codex_rollbacks\clip-download-storage-20261018-181203`; before SHA695aa727133348b713ca626cad7bed6baf7d4e711756649cc309a743c51e55af, after SHAbf8a3bae3a42b902d97067eaa89a31df325d50d74bb4a390ace5af70352b3614. Conditional code rollback and SHA manifest retained.
- Backend-only activation completed: `...\clip-download-activation-20261018-181232`, phasecomplete, database snapshot retained,0 captured control-plane groups. Existing remote work drained; GPU PID10424 unchanged. New library endpoint14545 returned206 video/mp4, Content-Range bytes0-0/194897271, exactly matching the probed2K artifact size. Only headers/range access checked, not a full video download.
- Recording-level45270 endpoint still reports `Clip not ready`, reflecting incomplete recording-level lifecycle, while its completed variant14545 remains registered/downloadable. This was not bypassed or relabeled as completion. Product/hairstyle identity checks and actual public publishing remain separate outstanding validation.

### 2026-10-18 Clip admission and startup recovery reliability

- Read-only audit: recording45270 completed with clipped2; requested clip_count3 does not guarantee3 material selections. Its historical variant_idx0 rows are retained.45266 and45298 were still clipped1. No row was artificially marked complete and no historical variants were deleted.
- Fresh production startup recovery checked only project/recordings to determine whether completed clips were missing; this could clear a valid configured-storage filename and enqueue an unnecessary reclip if the original MP4 remained in the legacy root. Existing `_recording_file_exists` now checks configured and legacy roots; startup recovery uses it for both output and source. Genuine missing-output/source-present and local_deleted behavior remain unchanged.
- Fresh production `_run_editor` could admit the same recording during validation or while already queued/running. Dispatcher could also start an ID already present in its running set, undercounting actual concurrent tasks. Added a thin admission reservation around the existing enqueue implementation and a running-ID dispatcher guard. Original production validation/LEFT JOIN/metadata behavior is retained. Reservations clear on exceptions; subsequent idle/manual generations remain allowed. This is process-local admission deduplication, not durable per-variant resume across service restarts.
-17 affected tests passed: concurrent validation/queued/running rejection and later acceptance; reservation release on failure; dispatcher duplicate guard; actual aiosqlite startup recovery with current/legacy files, truly missing output, missing source, intentionally-cleared source and stuck flags; prior download and backend-only activation tests.
- Commit43b074d pushed before source writes. Production backup: `C:\Users\neo\douyin_backend\codex_rollbacks\clip-recovery-20261018-182403`. Main after SHA82b38e7a722043445c7a2e1bba814317ea189e227bbe2b11e61970eafe4c72d5; transcribe after SHA1f615dbdd2a8000d3cd73d3b4c8c9d537597ff59b937ca3ebaca8b85f360c683. Conditional rollback restores only this code step, preserving2K/download/xfade/audio fixes. Database snapshot belongs to activation evidence; never blindly restore it over newer user data.
- Clip-recovery activation182519 timed out waiting for8899, but independent health/frontend checks returned200. Fresh logs established two launchers raced: a losing process ran startup recovery before Uvicorn failed to bind8899. Per-process admission guard correctly skipped duplicate IDs within each process, but cannot prevent startup work by competing processes.

### 2026-10-18 Database-scoped backend startup lock

- Added `backend_instance_lock.py` and a lifespan decorator in main. A nonblocking OS file lock is acquired before any original lifespan startup/recovery work; held through shutdown, released on startup failure and automatically on process termination. Lock file is based on resolved DB_PATH, retained to avoid unlink/recreate races. This prevents concurrent startup against the same database; it does not prevent an external supervisor from terminating and replacing the current process.
-15 targeted CPU tests passed, including subprocess exclusion, abrupt process exit, rejection before startup side effects, failure release and prior admission/storage routes. Additional Windows CPU subprocess check proved msvcrt exclusion/release in an isolated temporary directory. No competing live-backend test and no GPU workload submitted.
- Commit8b00314 pushed before deployment. Source backup `C:\Users\neo\douyin_backend\codex_rollbacks\backend-instance-lock-20261018-183354`; main SHA0821b6b6bf223ee0e15b73de8878660c3fee6792a138efee17a74b16cf1290fb; new module SHA18455d4128e9d16aa00d218d86198a4b811b14a2076597f820e061006ffee032. Manifest and drift-checked rollback preserve prior patches and remove only the new unchanged module when reverting. Stop/drain backend before rollback; never restore a stale database snapshot.
- Backend-only activation journal `...\backend-lock-activation-20261018-183415` reached backend_restored but its final GPU-status request was reset. Logs showed a first backend started successfully, then was replaced by another launcher; exact termination source remains unconfirmed. Did not repeat the entire deployment or disable unidentified supervisors. Independent checks found current backend PID12160 holding the production database lock, frontend/health/product739 link endpoint HTTP200, maintenancefalse and clip14545 range download206 bytes0-0/194897271. GPU PID10424 unchanged. Existing startup recovery resumed its own backlog; no manual bulk requeue/status edits.
- Remaining scope: investigate redundant launcher/supervisor replacement; durable per-variant resume; hairstyle identity quality; real public publishing remains untested. Historical duplicate variant rows and original recordings remain untouched.

### 2026-10-18 Resolve deployment supervisor race

- Read-only process ancestry identified active backend12160 owned by PowerShell13892 running production `backend/start_windows_backend.ps1`, scheduled task `DouyinBackend8899SusunInteractive`. Its production implementation calls `Stop-BackendFromOtherSession`, forcibly stops other-session Uvicorn processes, then restarts its own child after exit. The maintenance helper previously ended only Uvicorn8899 and the listener, leaving this interactive supervisor alive. This explains the repeated System→interactive process replacement during deployment. Production launcher differs from repository; it was not overwritten.
- Maintenance now inventories only known task identity/enabled/running flags (no action arguments/credentials), requires exactly one running owner, records original task state, disables known startup/guard triggers temporarily and ends the running supervisor before stopping its identified listener. It rejects a surviving listener before worker maintenance. Restores the original owner rather than always starting System Uvicorn8899, then reenables the two-minute guard only after readiness. Previously disabled tasks remain disabled. A failed readiness check records backend_restore_failed and leaves the guard paused with `restore_tasks.py`/task-state.json for explicit recovery; no automatic database restore.
-24 targeted CPU tests passed: prior startup-lock/admission/storage cases plus owner restoration/order, ambiguous-owner preflight rejection, guard remaining paused on readiness failure, full backend-only lifecycle without GPU restart and generated recovery-script compilation. Actual Windows read-only inventory succeeded. No real stop/start was performed solely to test maintenance.
- Commit59a8a9e pushed before tool deployment. Deployed `C:\Users\neo\douyin_backend\codex_operations\activate_remote_audio.py`; SHA9793da71321670a6960c0e680602336fb693c3146eccc57ea3db1ee145345355. Backup `...\codex_rollbacks\supervisor-maintenance-tool-20261018-191716` includes manifest, conditional tool-only rollback.py and verification.json. Tool was new; rollback removes it only if unchanged. Runtime launchers/tasks/config/database/media untouched. Tool defaults still enforce source hashes; future deployments must supply the current manifest-derived expected hashes as before.
-Post-deploy `--plan` selected the actual interactive owner; health/frontend/product739 URL editor/status all200, maintenancefalse; backend12160 unchanged. End-to-end owner pause/restart remains to be verified during the next necessary deployment, not represented as completed. Production session-switch restart policy remains unchanged and may still interrupt work when Windows sessions change; real publishing and hairstyle quality validation remain outstanding.
