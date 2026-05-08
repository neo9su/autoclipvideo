#!/usr/bin/env python3
"""
AI剧本到视频Prompt转换器
从现有76个导演模式剧本生成视频生成prompt
"""

import sqlite3
import json
from datetime import datetime

class ScriptToPromptConverter:
    def __init__(self):
        self.db_path = "/Users/claw/work/douyin-recorder/douyin.db"
        self.output_file = "ai_video_prompts.json"
        
    def extract_director_scripts(self):
        """从数据库提取导演模式剧本"""
        print("📜 提取导演模式剧本...")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query = """
            SELECT id, label, director_script 
            FROM clip_groups 
            WHERE editing_mode = 'director' 
            AND director_script IS NOT NULL 
            AND director_script != ''
            ORDER BY id
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            print(f"✅ 找到 {len(results)} 个带剧本的导演模式分组")
            
            scripts = []
            for group_id, label, script_json in results:
                try:
                    script = json.loads(script_json)
                    scripts.append({
                        'group_id': group_id,
                        'product_name': label,
                        'script': script
                    })
                except json.JSONDecodeError:
                    print(f"⚠️ 分组 {group_id} 剧本JSON解析失败")
            
            conn.close()
            return scripts
            
        except Exception as e:
            print(f"❌ 数据库读取错误: {e}")
            return []
    
    def convert_scene_to_video_prompt(self, scene, product_name):
        """将剧本场景转换为视频生成prompt"""
        
        # 场景类型到视觉风格映射
        scene_styles = {
            'opening': 'realistic lifestyle scene, natural lighting, relatable everyday moment',
            'discovery': 'product showcase style, studio lighting, elegant presentation', 
            'demonstration': 'before and after transformation, dramatic reveal, cinematic',
            'testimonial': 'authentic reaction, emotional expression, warm lighting',
            'closing': 'confident lifestyle shot, aspirational mood, bright lighting'
        }
        
        # 情绪到视觉描述映射
        emotion_visuals = {
            'frustrated': 'woman looking concerned in mirror, trying different looks, soft disappointed expression',
            'curious': 'woman examining product with interest, gentle smile forming, bright eyes',
            'amazed': 'dramatic transformation moment, surprise and delight expression, before/after split',
            'confident': 'woman feeling beautiful and confident, radiant smile, elegant posture',
            'urgent': 'close-up of product with subtle call-to-action energy, premium presentation'
        }
        
        base_style = scene_styles.get(scene.get('scene_type', 'opening'), 'realistic, natural lighting')
        emotion_visual = emotion_visuals.get(scene.get('emotion', '').split('_')[0], 'natural expression')
        
        # 提取关键视觉元素
        visual_requirements = scene.get('visual_requirements', [])
        visual_elements = ', '.join(visual_requirements) if visual_requirements else 'product focused scene'
        
        # 构建prompt
        prompt = f"{emotion_visual}, {visual_elements}, {base_style}, 4K quality, professional cinematography"
        
        return {
            'scene_id': scene.get('scene_id', 1),
            'scene_type': scene.get('scene_type', 'opening'),
            'duration': scene.get('timestamp_end', 10) - scene.get('timestamp_start', 0),
            'emotion': scene.get('emotion', 'neutral'),
            'original_description': scene.get('description', ''),
            'original_voiceover': scene.get('voiceover_text', ''),
            'video_prompt': prompt,
            'style_tags': ['4K', 'professional', 'realistic', 'commercial']
        }
    
    def convert_all_scripts_to_prompts(self):
        """转换所有剧本为视频prompt"""
        scripts = self.extract_director_scripts()
        
        if not scripts:
            print("❌ 没有找到可用的剧本")
            return
        
        print(f"🎬 开始转换 {len(scripts)} 个剧本...")
        
        all_prompts = []
        
        for script_data in scripts:
            group_id = script_data['group_id']
            product_name = script_data['product_name']
            script = script_data['script']
            
            print(f"  处理分组 {group_id}: {product_name}")
            
            # 转换所有场景
            scenes = script.get('scenes', [])
            group_prompts = {
                'group_id': group_id,
                'product_name': product_name,
                'script_type': script.get('script_type', 'story'),
                'total_duration': script.get('total_duration', 60),
                'narrative_structure': script.get('narrative_structure', ''),
                'video_prompts': []
            }
            
            for scene in scenes:
                video_prompt = self.convert_scene_to_video_prompt(scene, product_name)
                group_prompts['video_prompts'].append(video_prompt)
            
            all_prompts.append(group_prompts)
        
        # 保存结果
        output_data = {
            'generation_time': datetime.now().isoformat(),
            'total_groups': len(all_prompts),
            'total_scenes': sum(len(group['video_prompts']) for group in all_prompts),
            'prompts': all_prompts
        }
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 转换完成！共 {len(all_prompts)} 个分组")
        print(f"📁 结果已保存: {self.output_file}")
        
        return output_data
    
    def generate_test_selection(self, all_prompts, num_tests=10):
        """选择最佳测试样本"""
        print(f"🎯 选择 {num_tests} 个最佳测试样本...")
        
        # 选择标准：多样性 + 质量
        test_samples = []
        
        for i, group in enumerate(all_prompts['prompts'][:num_tests]):
            # 选择每个分组的第一个场景作为测试
            if group['video_prompts']:
                first_scene = group['video_prompts'][0]
                test_samples.append({
                    'test_id': i + 1,
                    'group_id': group['group_id'],
                    'product_name': group['product_name'],
                    'scene_type': first_scene['scene_type'],
                    'video_prompt': first_scene['video_prompt'],
                    'duration': first_scene['duration'],
                    'expected_style': 'Product showcase, lifestyle commercial'
                })
        
        test_file = "ai_video_test_prompts.json"
        with open(test_file, 'w', encoding='utf-8') as f:
            json.dump({
                'generation_time': datetime.now().isoformat(),
                'test_count': len(test_samples),
                'test_samples': test_samples
            }, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 测试样本已保存: {test_file}")
        
        # 显示前3个样本
        print("\\n📋 测试样本预览:")
        for sample in test_samples[:3]:
            print(f"  {sample['test_id']}. {sample['product_name']}")
            print(f"     Prompt: {sample['video_prompt'][:80]}...")
            print(f"     时长: {sample['duration']}秒")
            print("")
        
        return test_samples
    
    def generate_cost_estimates(self, test_samples):
        """生成成本估算"""
        print("💰 AI视频生成成本估算:")
        print("-" * 25)
        
        # API服务成本
        services = {
            'Stability AI': {'cost_per_video': 0.05, 'quality': '高', 'speed': '2-5分钟'},
            'Runway Gen-3': {'cost_per_video': 3.00, 'quality': '商业级', 'speed': '1-3分钟'},
            'Pika Labs': {'cost_per_video': 2.00, 'quality': '高', 'speed': '30-60秒'},
        }
        
        num_tests = len(test_samples)
        
        for service, details in services.items():
            test_cost = num_tests * details['cost_per_video']
            monthly_1000 = 1000 * details['cost_per_video']
            
            print(f"📊 {service}:")
            print(f"  {num_tests}个测试视频: ${test_cost:.2f}")
            print(f"  月产1000个视频: ${monthly_1000:.2f}")
            print(f"  质量等级: {details['quality']}")
            print(f"  生成速度: {details['speed']}")
            print("")

def main():
    converter = ScriptToPromptConverter()
    
    print("🎬 AI剧本到视频Prompt转换器")
    print("=" * 30)
    print(f"📅 转换时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("")
    
    # 转换所有剧本
    all_prompts = converter.convert_all_scripts_to_prompts()
    
    if all_prompts:
        # 生成测试样本
        test_samples = converter.generate_test_selection(all_prompts, 10)
        
        # 生成成本估算
        converter.generate_cost_estimates(test_samples)
        
        print("🎯 下一步行动:")
        print("1. 注册Stability AI账号 (最便宜选项)")
        print("2. 使用ai_video_test_prompts.json中的prompt测试生成")
        print("3. 评估生成质量并与录屏视频对比")
        print("4. 制定正式部署策略")
    else:
        print("❌ 未找到可用剧本，请检查数据库状态")

if __name__ == "__main__":
    main()